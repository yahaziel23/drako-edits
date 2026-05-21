#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Revisar Memes Manualmente

Abre cada imagen descargada y te pregunta si la quieres mantener o desechar.
- Mantener: se queda en memes_descargados/ (lista para clasificar en paso 3)
- Desechar: se BORRA de memes_descargados/ y se registra en historial/descartados_manual.json
  (asi no se vuelve a descargar ni se manda a clasificar)

El shortcode sigue en posts_descargados.json (el paso 2 no lo re-descarga).

Uso:
    python revisar_memes.py              # Revisa todos los pendientes
    python revisar_memes.py --max 20     # Solo revisa 20
    python revisar_memes.py --sin-abrir  # No abre imagen (solo muestra nombre)
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
HISTORIAL_DIR = SCRIPT_DIR / "historial"
DESCARTADOS_FILE = HISTORIAL_DIR / "descartados_manual.json"
DOWNLOADS_FILE = HISTORIAL_DIR / "posts_descargados.json"
CLASIFICACIONES_FILE = HISTORIAL_DIR / "clasificaciones.json"


# =============================================================================
# FUNCIONES
# =============================================================================

def load_descartados():
    """Carga historial de memes descartados."""
    if DESCARTADOS_FILE.exists():
        try:
            return json.loads(DESCARTADOS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"descartados": [], "mantenidos": []}


def save_descartados(data):
    """Guarda historial de descartados."""
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    DESCARTADOS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_downloads_log():
    """Carga historial de descargas para saber tipo y metricas."""
    if DOWNLOADS_FILE.exists():
        try:
            return json.loads(DOWNLOADS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"descargados_foto": [], "descargados_frame": [], "skipped_carousels": [], "skipped_low_likes": [], "errores": []}


def load_clasificaciones():
    """Carga clasificaciones previas."""
    if CLASIFICACIONES_FILE.exists():
        try:
            return json.loads(CLASIFICACIONES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clasificados": [], "skipped_video_content": [], "errores": []}


def get_post_info(shortcode, downloads_log):
    """
    Obtiene tipo y metricas de un shortcode desde el log de descargas.
    Returns: dict con source_type, likes, comments, views
    """
    for item in downloads_log.get("descargados_foto", []):
        if item["shortcode"] == shortcode:
            return {
                "source_type": "foto",
                "likes": item.get("likes", "?"),
                "comments": item.get("comments", "?"),
                "views": item.get("views", None),
            }
    for item in downloads_log.get("descargados_frame", []):
        if item["shortcode"] == shortcode:
            return {
                "source_type": "frame (screenshot de video)",
                "likes": item.get("likes", "?"),
                "comments": item.get("comments", "?"),
                "views": item.get("views", None),
            }
    return {"source_type": "desconocido", "likes": "?", "comments": "?", "views": None}


def format_number(n):
    """Formatea numero con separador de miles."""
    if n is None or n == "?":
        return "?"
    if isinstance(n, int):
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n/1_000:.1f}K"
        return str(n)
    return str(n)


def get_pending_review(descartados_data, clasificaciones):
    """
    Obtiene imagenes que aun no han sido revisadas manualmente NI clasificadas.
    """
    if not MEMES_DIR.exists():
        return []

    # Ya revisados (descartados + mantenidos)
    ya_revisados = set()
    for item in descartados_data.get("descartados", []):
        ya_revisados.add(item["shortcode"])
    for item in descartados_data.get("mantenidos", []):
        ya_revisados.add(item["shortcode"])

    # Ya clasificados por IA (esos ya pasaron, no necesitan revision manual)
    for item in clasificaciones.get("clasificados", []):
        ya_revisados.add(item["shortcode"])
    for item in clasificaciones.get("skipped_video_content", []):
        ya_revisados.add(item["shortcode"])

    # Buscar imagenes no revisadas
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    pending = []
    for f in sorted(MEMES_DIR.iterdir()):
        if f.suffix.lower() in image_extensions:
            shortcode = f.stem
            if shortcode not in ya_revisados:
                pending.append(f)

    return pending


def open_image(image_path):
    """Abre imagen con el visor por defecto del sistema."""
    try:
        if sys.platform == "win32":
            os.startfile(str(image_path))
        elif sys.platform == "darwin":  # macOS
            os.system(f'open "{image_path}"')
        else:  # Linux
            os.system(f'xdg-open "{image_path}"')
        return True
    except Exception as e:
        print(f"       [!] No pude abrir la imagen: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def main():
    parser = argparse.ArgumentParser(description="Revisar memes manualmente")
    parser.add_argument("--max", type=int, default=None,
                        help="Maximo de memes a revisar (default: todos)")
    parser.add_argument("--sin-abrir", action="store_true",
                        help="No abre la imagen (solo muestra nombre)")
    args = parser.parse_args()

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - REVISAR MEMES MANUALMENTE")
    print(SEPARATOR_EQ)
    print("   Controles:")
    print("     s / Enter  = MANTENER (se queda para clasificar)")
    print("     n / d      = DESECHAR (se borra, no se clasifica)")
    print("     q          = SALIR (guardar y terminar)")
    print(SEPARATOR_EQ)

    # Cargar datos
    descartados_data = load_descartados()
    downloads_log = load_downloads_log()
    clasificaciones = load_clasificaciones()

    # Obtener pendientes
    pending = get_pending_review(descartados_data, clasificaciones)

    if not pending:
        print("\n   [!] No hay memes pendientes de revisar.")
        total_d = len(descartados_data.get("descartados", []))
        total_m = len(descartados_data.get("mantenidos", []))
        print(f"       Descartados: {total_d}  |  Mantenidos: {total_m}")
        return

    # Limitar si --max
    if args.max:
        pending = pending[:args.max]

    print(f"\n   Pendientes de revisar: {len(pending)}")
    print(SEPARATOR)

    stats = {"mantenidos": 0, "descartados": 0}

    for i, image_path in enumerate(pending):
        shortcode = image_path.stem
        info = get_post_info(shortcode, downloads_log)
        source = info["source_type"]
        likes = format_number(info["likes"])
        comments = format_number(info["comments"])
        views = format_number(info["views"])

        print(f"\n   [{i+1}/{len(pending)}] {shortcode}")
        print(f"       Tipo: {source}")
        likes_str = f"       Likes: {likes}  |  Comments: {comments}"
        if info["views"] is not None:
            likes_str += f"  |  Views: {views}"
        print(likes_str)
        print(f"       Archivo: {image_path.name}")

        # Abrir imagen
        if not args.sin_abrir:
            open_image(image_path)

        # Pedir decision
        while True:
            choice = input("       Mantener? (s/Enter=si, n/d=desechar, q=salir): ").strip().lower()
            if choice in ("", "s", "si", "y", "yes"):
                # MANTENER
                stats["mantenidos"] += 1
                descartados_data["mantenidos"].append({
                    "shortcode": shortcode,
                    "source_type": source,
                    "likes": info["likes"],
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                print("       -> MANTENIDO")
                break
            elif choice in ("n", "d", "no", "delete", "borrar"):
                # DESECHAR - borrar archivo, registrar
                stats["descartados"] += 1
                descartados_data["descartados"].append({
                    "shortcode": shortcode,
                    "source_type": source,
                    "likes": info["likes"],
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                # Borrar archivo
                try:
                    image_path.unlink()
                    print("       -> DESCARTADO (archivo borrado)")
                except Exception as e:
                    print(f"       -> DESCARTADO (no pude borrar: {e})")
                break
            elif choice in ("q", "quit", "salir"):
                print("\n   [SALIR] Guardando progreso...")
                save_descartados(descartados_data)
                _print_summary(stats, descartados_data)
                return
            else:
                print("       [?] Opcion no valida. Usa: s/Enter, n/d, q")

        # Guardar despues de cada decision (por si se cierra)
        save_descartados(descartados_data)

    # Resumen final
    _print_summary(stats, descartados_data)


def _print_summary(stats, descartados_data):
    """Muestra resumen final."""
    print("")
    print(SEPARATOR_EQ)
    print("   RESUMEN DE SESION")
    print(SEPARATOR_EQ)
    print(f"   Mantenidos esta sesion: {stats['mantenidos']}")
    print(f"   Descartados esta sesion: {stats['descartados']}")
    print(f"")
    print(f"   TOTALES HISTORICOS:")
    print(f"     Total mantenidos: {len(descartados_data.get('mantenidos', []))}")
    print(f"     Total descartados: {len(descartados_data.get('descartados', []))}")
    print(f"   Guardado en: {DESCARTADOS_FILE}")
    print(SEPARATOR_EQ)


if __name__ == "__main__":
    main()
