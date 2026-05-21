#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 2: Descarga de Memes (instaloader SIN LOGIN)

Lee shortcodes de historial/links_scrapeados.json (campo 'por_descargar').
Para cada uno:
  - Consulta tipo con Post.from_shortcode()
  - GraphImage (foto simple) -> descarga directa
  - GraphVideo -> extrae primer frame como imagen (muchos son fotos con audio)
  - GraphSidecar (carousel) -> skip

CADA Post.from_shortcode() CUENTA COMO 1 REQUEST a Instagram
(sin importar si descargas o no). --max limita requests totales.

Protecciones anti-ban:
  - Delay de 5s entre requests
  - Pausa larga (3 min) cada 20 posts procesados
  - Límite máximo de posts por sesión (default: 50)
  - Si detecta error (rate limit, login required) -> para y guarda progreso

Output: memes_descargados/{shortcode}.jpg

Uso:
    python 2_download_memes.py
    python 2_download_memes.py --max 10

Dependencias: instaloader, Pillow (para frames de video si se usa ffmpeg)
"""

import json
import sys
import os
import time
import random
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

try:
    import instaloader
except ImportError:
    print("   [X] Necesitas instalar instaloader:")
    print("       pip install instaloader")
    sys.exit(1)


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
HISTORIAL_DIR = SCRIPT_DIR / "historial"
LINKS_FILE = HISTORIAL_DIR / "links_scrapeados.json"
DOWNLOADS_FILE = HISTORIAL_DIR / "posts_descargados.json"
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
TEMP_DIR = SCRIPT_DIR / "_temp_video"

# --- RATE LIMITING ---
MAX_POR_SESION = 50       # Máximo de posts a procesar por ejecución
DELAY_ENTRE_POSTS = 5     # Segundos entre cada request
PAUSA_CADA_N = 20         # Cada cuántos posts hacer pausa larga
PAUSA_DURACION = 180      # Segundos de pausa larga (3 min)


# =============================================================================
# FUNCIONES
# =============================================================================

def load_links():
    """Carga links scrapeados."""
    if LINKS_FILE.exists():
        try:
            return json.loads(LINKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"scrapeados": [], "por_descargar": []}


def save_links(data):
    """Guarda links actualizados."""
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    LINKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_downloads_log():
    """Carga historial de descargas."""
    if DOWNLOADS_FILE.exists():
        try:
            return json.loads(DOWNLOADS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "descargados_foto": [],
        "descargados_frame": [],
        "skipped_carousels": [],
        "errores": []
    }


def save_downloads_log(data):
    """Guarda historial de descargas."""
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOADS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_instaloader():
    """Crea instancia de instaloader SIN LOGIN."""
    L = instaloader.Instaloader(
        download_videos=True,  # Necesitamos descargar video para extraer frame
        download_video_thumbnails=False,
        download_comments=False,
        download_geotags=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        filename_pattern="{shortcode}",
    )
    return L


def extract_first_frame(video_path, output_path):
    """
    Extrae el primer frame de un video usando ffmpeg.
    Muchos "videos" de IG son fotos con audio, así que el primer frame = el meme.
    
    Returns:
        bool: True si se extrajo exitosamente
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",  # Alta calidad JPEG
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
            return True
        else:
            return False
    except Exception:
        return False


def process_shortcode(L, shortcode, stats):
    """
    Procesa un shortcode: verifica tipo y actúa según el caso.
    
    - GraphImage: descarga foto directamente
    - GraphVideo: descarga video, extrae primer frame, borra video
    - GraphSidecar: skip (carousel)
    
    Returns:
        str: 'foto', 'frame', 'skip_carousel', 'error', 'rate_limit'
    """
    counter = f"[{stats['processed']}/{stats['total']}]"
    
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
    except instaloader.exceptions.QueryReturnedNotFoundException:
        print(f"   {counter} {shortcode} -> [X] No encontrado (borrado?)")
        return "error"
    except instaloader.exceptions.ConnectionException as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate" in error_str or "login" in error_str or "redirect" in error_str:
            print(f"   {counter} {shortcode} -> [X] RATE LIMIT / LOGIN REQUIRED")
            print("   [!!!] Deteniendo para evitar ban. Progreso guardado.")
            return "rate_limit"
        print(f"   {counter} {shortcode} -> [X] Error conexión: {e}")
        return "error"
    except Exception as e:
        print(f"   {counter} {shortcode} -> [X] Error: {e}")
        return "error"

    typename = post.typename
    MEMES_DIR.mkdir(parents=True, exist_ok=True)

    # === FOTO SIMPLE ===
    if typename == "GraphImage":
        try:
            L.download_post(post, target=str(MEMES_DIR))
            # Limpiar archivos extra que instaloader puede crear
            _cleanup_instaloader_extras(shortcode)
            print(f"   {counter} {shortcode} -> [OK] foto descargada")
            return "foto"
        except Exception as e:
            print(f"   {counter} {shortcode} -> [X] Error descargando: {e}")
            return "error"

    # === VIDEO -> EXTRAER PRIMER FRAME ===
    elif typename == "GraphVideo":
        try:
            # Descargar video a carpeta temporal
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            L.download_post(post, target=str(TEMP_DIR))
            
            # Buscar el archivo de video descargado
            video_file = None
            for f in TEMP_DIR.iterdir():
                if f.suffix.lower() in ('.mp4', '.webm', '.mov') and shortcode in f.name:
                    video_file = f
                    break
            
            if not video_file:
                # Buscar cualquier video en temp
                for f in TEMP_DIR.iterdir():
                    if f.suffix.lower() in ('.mp4', '.webm', '.mov'):
                        video_file = f
                        break
            
            if not video_file:
                print(f"   {counter} {shortcode} -> [X] Video no encontrado en temp")
                _cleanup_temp()
                return "error"
            
            # Extraer primer frame
            output_frame = MEMES_DIR / f"{shortcode}.jpg"
            success = extract_first_frame(video_file, output_frame)
            
            # Limpiar temp
            _cleanup_temp()
            
            if success:
                print(f"   {counter} {shortcode} -> [OK] frame extraído (era video/foto+audio)")
                return "frame"
            else:
                print(f"   {counter} {shortcode} -> [X] No se pudo extraer frame")
                return "error"
                
        except Exception as e:
            print(f"   {counter} {shortcode} -> [X] Error procesando video: {e}")
            _cleanup_temp()
            return "error"

    # === CAROUSEL -> SKIP ===
    elif typename == "GraphSidecar":
        print(f"   {counter} {shortcode} -> skip (carousel)")
        return "skip_carousel"

    else:
        print(f"   {counter} {shortcode} -> skip (tipo desconocido: {typename})")
        return "skip_carousel"


def _cleanup_instaloader_extras(shortcode):
    """Limpia archivos extra que instaloader crea (json, txt, etc)."""
    for f in MEMES_DIR.iterdir():
        if shortcode in f.name and f.suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
            f.unlink(missing_ok=True)


def _cleanup_temp():
    """Limpia carpeta temporal de videos."""
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR, ignore_errors=True)


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def main():
    parser = argparse.ArgumentParser(description="Paso 2: Descargar memes")
    parser.add_argument("--max", type=int, default=MAX_POR_SESION,
                        help=f"Máximo de posts a PROCESAR (default: {MAX_POR_SESION}). Cada uno = 1 request a IG.")
    args = parser.parse_args()
    max_sesion = args.max

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 2: DESCARGA DE MEMES")
    print(SEPARATOR_EQ)
    print(f"   Máximo por sesión: {max_sesion} (cada uno = 1 request a IG)")
    print(f"   Delay entre posts: {DELAY_ENTRE_POSTS}s")
    print(f"   Pausa cada {PAUSA_CADA_N} posts: {PAUSA_DURACION}s ({PAUSA_DURACION//60} min)")
    print(f"   Carpeta destino: {MEMES_DIR}")
    print("")
    print("   Comportamiento por tipo:")
    print("     GraphImage   -> descarga foto directa")
    print("     GraphVideo   -> extrae primer frame (foto con audio)")
    print("     GraphSidecar -> skip (carousel)")

    # Cargar pendientes
    links_data = load_links()
    por_descargar = links_data.get("por_descargar", [])

    if not por_descargar:
        print("\n   [!] No hay shortcodes pendientes de descargar.")
        print("       Ejecuta primero: python 1_scrape_meme_links.py")
        return

    print(f"\n   Pendientes de descargar: {len(por_descargar)}")

    # Limitar a max_sesion
    batch = por_descargar[:max_sesion]
    print(f"   Procesando en esta sesión: {len(batch)}")

    # Cargar historial de descargas
    downloads_log = load_downloads_log()

    # Crear instaloader
    L = create_instaloader()

    # Procesar
    print("")
    print(SEPARATOR)
    print("   PROCESANDO...")
    print(SEPARATOR)

    stats = {
        "processed": 0,
        "total": len(batch),
        "fotos": 0,
        "frames": 0,
        "skipped_carousel": 0,
        "errores": 0,
    }
    processed_shortcodes = []
    stopped_early = False

    for i, shortcode in enumerate(batch):
        stats["processed"] = i + 1

        # Pausa larga cada N posts
        if i > 0 and i % PAUSA_CADA_N == 0:
            print(f"\n   [PAUSA] {PAUSA_DURACION}s ({PAUSA_DURACION//60} min) - evitar rate limit...")
            time.sleep(PAUSA_DURACION)
            print("   [OK] Continuando...\n")

        # Procesar
        result = process_shortcode(L, shortcode, stats)

        if result == "rate_limit":
            stopped_early = True
            break

        # Registrar resultado
        processed_shortcodes.append(shortcode)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if result == "foto":
            stats["fotos"] += 1
            downloads_log["descargados_foto"].append({"shortcode": shortcode, "fecha": now})
        elif result == "frame":
            stats["frames"] += 1
            downloads_log["descargados_frame"].append({"shortcode": shortcode, "fecha": now})
        elif result == "skip_carousel":
            stats["skipped_carousel"] += 1
            downloads_log["skipped_carousels"].append(shortcode)
        elif result == "error":
            stats["errores"] += 1
            downloads_log["errores"].append({"shortcode": shortcode, "fecha": now})

        # Delay entre posts
        if i < len(batch) - 1 and not stopped_early:
            delay = DELAY_ENTRE_POSTS + random.uniform(0, 2)
            time.sleep(delay)

    # Guardar progreso
    links_data["por_descargar"] = [sc for sc in por_descargar if sc not in processed_shortcodes]
    save_links(links_data)
    save_downloads_log(downloads_log)

    # Limpiar temp por si quedó algo
    _cleanup_temp()

    # Resumen
    print("")
    print(SEPARATOR_EQ)
    print("   RESUMEN")
    print(SEPARATOR_EQ)
    print(f"   Procesados: {stats['processed']} requests a IG")
    print(f"   Fotos descargadas: {stats['fotos']}")
    print(f"   Frames extraídos (video/foto+audio): {stats['frames']}")
    print(f"   Carousels (skip): {stats['skipped_carousel']}")
    print(f"   Errores: {stats['errores']}")
    print(f"   Total imágenes guardadas: {stats['fotos'] + stats['frames']}")
    print(f"   Pendientes restantes: {len(links_data['por_descargar'])}")
    if stopped_early:
        print("   [!] Se detuvo por rate limit. Corre de nuevo más tarde.")
    print(f"   Carpeta: {MEMES_DIR}")
    print(SEPARATOR_EQ)


if __name__ == "__main__":
    main()
