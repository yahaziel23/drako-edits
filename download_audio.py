#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descargador de audio de YouTube Shorts

Descarga solo el audio de un Short para usarlo como musica de fondo
en los videos de meme_reaction.

Uso:
    python download_audio.py
    python download_audio.py --url "https://www.youtube.com/shorts/XXXXX"
    python download_audio.py --url "https://www.youtube.com/shorts/XXXXX" --name "flexeo_epico"
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

SCRIPT_DIR = Path(__file__).parent
MUSIC_DIR = SCRIPT_DIR / "assets" / "meme_reaction" / "music"


# =============================================================================
# FUNCIONES
# =============================================================================

def download_audio(url, filename):
    """Descarga solo el audio de un YouTube Short como MP3."""
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    output_path = MUSIC_DIR / filename

    print(f"\n   Descargando audio...")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "-o", str(output_path),
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
        MUSIC_DIR / (output_path.stem + ".mp3"),
    ]
    for f in possible_files:
        if f.exists():
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"   [OK] Descargado: {f.name} ({size_mb:.2f} MB)")
            return f

    print(f"   [X] No se encontro el archivo descargado")
    return None


def interactive_download():
    """Flujo interactivo para descargar audio."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGADOR DE AUDIO")
    print("=" * 60)

    # Mostrar audios existentes
    existing = list(MUSIC_DIR.glob("*.mp3")) if MUSIC_DIR.exists() else []
    if existing:
        print(f"\n   Audios en la carpeta: {len(existing)}")
        for f in sorted(existing):
            size = f.stat().st_size / (1024 * 1024)
            print(f"     - {f.name} ({size:.2f} MB)")

    # 1. Pedir URL
    print("\n--- PASO 1: Link del Short ---")
    url = input("\n   Pega el link del YouTube Short: ").strip()
    if not url:
        print("   [X] No pusiste link. Saliendo.")
        return

    # 2. Pedir nombre
    print("\n--- PASO 2: Nombre del archivo ---")
    print("   (sin extension, usa guion_bajo, ej: flexeo_epico)")
    print("   Tip: usa nombres descriptivos del vibe (flexeo, triste, hype, chill)")
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
        print(f"\n   [OK] Audio guardado en: {result}")
        print(f"   Listo para usar en generate_meme_reaction.py")
    
    # Preguntar si quiere descargar otro
    otro = input("\n   Descargar otro audio? (s/n): ").strip().lower()
    if otro == 's':
        interactive_download()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - Descargar audio")
    parser.add_argument("--url", type=str, default=None,
                        help="URL del YouTube Short")
    parser.add_argument("--name", type=str, default=None,
                        help="Nombre del archivo (sin extension)")
    args = parser.parse_args()

    # Modo directo si pasan url y name
    if args.url and args.name:
        filename = args.name if args.name.endswith(".mp3") else args.name + ".mp3"
        download_audio(args.url, filename)
    else:
        interactive_download()
