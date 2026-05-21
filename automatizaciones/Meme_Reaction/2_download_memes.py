#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 2: Descarga de Memes (instaloader SIN LOGIN)

Lee shortcodes de historial/links_scrapeados.json (campo 'por_descargar').
Para cada uno:
  - Consulta tipo con Post.from_shortcode() (1 request a IG)
  - GraphImage -> descarga imagen directa con requests
  - GraphVideo -> descarga video con requests, extrae frame con ffmpeg, borra video
  - GraphSidecar -> skip (carousel)

NOTA: NO usa instaloader.download_post() porque tiene un bug de paths en Windows
(convierte rutas absolutas en nombres de carpeta con caracteres full-width).
Solo usa instaloader para obtener el tipo y URL del post.

Protecciones anti-ban:
  - Delay de 5s entre requests
  - Pausa larga (3 min) cada 20 posts procesados
  - Límite máximo de posts por sesión (default: 50)
  - Auto-stop si detecta rate limit / login required

Output: memes_descargados/{shortcode}.jpg

Uso:
    python 2_download_memes.py
    python 2_download_memes.py --max 10

Dependencias: instaloader, requests
"""

import json
import sys
import time
import random
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

import requests as req

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
    """Crea instancia de instaloader SIN LOGIN (solo para queries, no para download)."""
    L = instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_comments=False,
        download_geotags=False,
        save_metadata=False,
    )
    return L


def download_file(url, output_path):
    """
    Descarga un archivo de una URL directamente con requests.
    Evita el bug de paths de instaloader en Windows.
    """
    try:
        response = req.get(url, stream=True, timeout=60)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path.exists() and output_path.stat().st_size > 1000
    except Exception as e:
        print(f"       [X] Error descargando archivo: {e}")
        return False


def extract_first_frame(video_path, output_path):
    """
    Extrae el primer frame de un video usando ffmpeg.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000
    except Exception:
        return False


def process_shortcode(L, shortcode, stats):
    """
    Procesa un shortcode:
    1. Obtiene info del post con instaloader (1 request a IG)
    2. Según el tipo, descarga con requests (NO usa instaloader.download_post)
    
    Returns:
        str: 'foto', 'frame', 'skip_carousel', 'error', 'rate_limit'
    """
    counter = f"[{stats['processed']}/{stats['total']}]"

    # === PASO 1: Obtener info del post ===
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
    except instaloader.exceptions.QueryReturnedNotFoundException:
        print(f"   {counter} {shortcode} -> [X] No encontrado (borrado?)")
        return "error"
    except instaloader.exceptions.ConnectionException as e:
        error_str = str(e).lower()
        if "429" in error_str or "rate" in error_str or "login" in error_str or "redirect" in error_str or "403" in error_str:
            print(f"   {counter} {shortcode} -> [X] RATE LIMIT / BLOCKED")
            print("   [!!!] Deteniendo para evitar ban. Progreso guardado.")
            return "rate_limit"
        print(f"   {counter} {shortcode} -> [X] Error conexión: {e}")
        return "error"
    except Exception as e:
        print(f"   {counter} {shortcode} -> [X] Error: {e}")
        return "error"

    typename = post.typename
    MEMES_DIR.mkdir(parents=True, exist_ok=True)

    # === GRAPHIMAGE: Descargar foto directa ===
    if typename == "GraphImage":
        image_url = post.url
        output_path = MEMES_DIR / f"{shortcode}.jpg"
        success = download_file(image_url, output_path)
        if success:
            print(f"   {counter} {shortcode} -> [OK] foto descargada")
            return "foto"
        else:
            print(f"   {counter} {shortcode} -> [X] Error descargando imagen")
            return "error"

    # === GRAPHVIDEO: Descargar video, extraer frame, borrar video ===
    elif typename == "GraphVideo":
        video_url = post.video_url
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        temp_video_path = TEMP_DIR / f"{shortcode}.mp4"
        output_frame_path = MEMES_DIR / f"{shortcode}.jpg"

        # Descargar video
        success_download = download_file(video_url, temp_video_path)
        if not success_download:
            print(f"   {counter} {shortcode} -> [X] Error descargando video")
            _cleanup_temp()
            return "error"

        # Extraer primer frame
        success_frame = extract_first_frame(temp_video_path, output_frame_path)
        _cleanup_temp()

        if success_frame:
            print(f"   {counter} {shortcode} -> [OK] frame extraído (video/foto+audio)")
            return "frame"
        else:
            print(f"   {counter} {shortcode} -> [X] Error extrayendo frame")
            return "error"

    # === GRAPHSIDECAR: Skip ===
    elif typename == "GraphSidecar":
        print(f"   {counter} {shortcode} -> skip (carousel)")
        return "skip_carousel"

    else:
        print(f"   {counter} {shortcode} -> skip (tipo: {typename})")
        return "skip_carousel"


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
    print("     GraphImage   -> descarga foto directa (con requests)")
    print("     GraphVideo   -> descarga video, extrae frame, borra video")
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

    # Crear instaloader (solo para queries)
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
