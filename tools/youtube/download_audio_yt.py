#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descargador de Audio de YouTube

Descarga solo el audio (MP3) de cualquier URL de YouTube:
shorts, videos normales, musica, etc. Usa yt-dlp.

Output: tools_output/audios/

Uso:
    python tools/youtube/download_audio_yt.py
    python tools/youtube/download_audio_yt.py --url "https://www.youtube.com/watch?v=XXXXX"
    python tools/youtube/download_audio_yt.py --url "https://www.youtube.com/shorts/XXXXX" --name "beat_epico"
"""

import subprocess
import argparse
import sys
import io
from pathlib import Path

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent.parent  # raiz del proyecto
OUTPUT_DIR = SCRIPT_DIR / "tools_output" / "audios"


# =============================================================================
# FUNCIONES
# =============================================================================

def download_audio(url, filename):
    """
    Descarga solo el audio de un video de YouTube como MP3.

    Args:
        url: URL de YouTube (short, video normal, etc.)
        filename: Nombre del archivo de salida (con .mp3)
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / filename

    print(f"\n   Descargando audio...")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", str(output_path.with_suffix("")),
        "--no-playlist",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   [X] Error: {result.stderr[:300]}")
        return None

    # yt-dlp a veces agrega extension extra, buscar el archivo
    possible_files = [
        output_path,
        output_path.with_suffix(".mp3"),
        OUTPUT_DIR / (output_path.stem + ".mp3"),
    ]
    for f in possible_files:
        if f.exists():
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"   [OK] Descargado: {f.name} ({size_mb:.2f} MB)")
            print(f"   [OK] Guardado en: {f}")
            return f

    print(f"   [X] No se encontro el archivo descargado")
    return None


def interactive_download():
    """Flujo interactivo para descargar audio."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGADOR DE AUDIO (YouTube)")
    print("=" * 60)

    # Mostrar audios existentes
    existing = list(OUTPUT_DIR.glob("*.mp3")) if OUTPUT_DIR.exists() else []
    if existing:
        print(f"\n   Audios descargados previamente: {len(existing)}")
        for f in sorted(existing)[-5:]:
            size = f.stat().st_size / (1024 * 1024)
            print(f"     - {f.name} ({size:.2f} MB)")
        if len(existing) > 5:
            print(f"     ... y {len(existing) - 5} mas")

    # 1. Pedir URL
    print("\n--- PASO 1: Link del video ---")
    print("   (Funciona con Shorts, videos normales, musica, etc.)")
    url = input("\n   Pega el link de YouTube: ").strip()
    if not url:
        print("   [X] No pusiste link. Saliendo.")
        return

    # 2. Pedir nombre
    print("\n--- PASO 2: Nombre del archivo ---")
    print("   (sin extension, usa guion_bajo, ej: beat_epico)")
    print("   Tip: usa nombres del vibe (flexeo, triste, hype, chill, epico)")
    filename = input("   Nombre: ").strip()
    if not filename:
        print("   [X] No pusiste nombre. Saliendo.")
        return
    if not filename.endswith(".mp3"):
        filename += ".mp3"

    # 3. Descargar
    print("\n--- PASO 3: Descargando ---")
    result = download_audio(url, filename)

    if result:
        print(f"\n   >>> Listo para usar en tus edits!")

    # Otro?
    otro = input("\n   Descargar otro audio? (s/n): ").strip().lower()
    if otro == 's':
        interactive_download()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - Descargar audio de YouTube")
    parser.add_argument("--url", type=str, default=None,
                        help="URL de YouTube (short, video normal, etc.)")
    parser.add_argument("--name", type=str, default=None,
                        help="Nombre del archivo (sin extension)")
    args = parser.parse_args()

    # Modo directo si pasan url y name
    if args.url and args.name:
        filename = args.name if args.name.endswith(".mp3") else args.name + ".mp3"
        download_audio(args.url, filename)
    else:
        interactive_download()
