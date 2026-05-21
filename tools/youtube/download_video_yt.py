#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descargador de Video de YouTube

Descarga videos de cualquier URL de YouTube (shorts, normales, etc.)
Te pregunta si quieres con o sin audio:
  - Con audio:    se guarda como "{nombre} (audio).mp4"
                  + AUTOMATICAMENTE guarda audio aparte como "{nombre} (only audio).mp3"
  - Sin audio:    se guarda como "{nombre} (sinaudio).mp4"
                  + te pregunta si quieres descargar el audio aparte (MP3)

Output videos: tools_output/videos/
Output audios: tools_output/audios/

Uso:
    python tools/youtube/download_video_yt.py
    python tools/youtube/download_video_yt.py --url "https://..." --name "clip" --mode audio
    python tools/youtube/download_video_yt.py --url "https://..." --name "clip" --mode sinaudio
    python tools/youtube/download_video_yt.py --url "https://..." --name "clip" --mode sinaudio --also-audio --audio-name "beat"
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
VIDEOS_DIR = SCRIPT_DIR / "tools_output" / "videos"
AUDIOS_DIR = SCRIPT_DIR / "tools_output" / "audios"


# =============================================================================
# FUNCIONES
# =============================================================================

def download_video(url, filename, include_audio=True):
    """
    Descarga un video de YouTube.

    Args:
        url: URL de YouTube (short, video normal, etc.)
        filename: Nombre completo del archivo (con .mp4)
        include_audio: Si True descarga video+audio, si False solo video
    """
    VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = VIDEOS_DIR / filename

    print(f"\n   Descargando video {'(con audio)' if include_audio else '(sin audio)'}...")

    if include_audio:
        fmt = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b"
    else:
        fmt = "bv[ext=mp4]"

    cmd = [
        "yt-dlp",
        "-f", fmt,
        "-o", str(output_path),
        "--no-playlist",
        "--merge-output-format", "mp4",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   [X] Error: {result.stderr[:300]}")
        return None

    # yt-dlp puede agregar extension extra
    possible_files = [
        output_path,
        output_path.with_suffix(".mp4"),
        VIDEOS_DIR / (output_path.stem + ".mp4"),
    ]
    for f in possible_files:
        if f.exists():
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"   [OK] Video: {f.name} ({size_mb:.2f} MB)")
            print(f"   [OK] En: {f}")
            return f

    print(f"   [X] No se encontro el archivo descargado")
    return None


def download_audio(url, filename):
    """
    Descarga solo el audio de un video de YouTube como MP3.

    Args:
        url: URL de YouTube
        filename: Nombre completo del archivo (con .mp3)
    """
    AUDIOS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AUDIOS_DIR / filename

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

    possible_files = [
        output_path,
        output_path.with_suffix(".mp3"),
        AUDIOS_DIR / (output_path.stem + ".mp3"),
    ]
    for f in possible_files:
        if f.exists():
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"   [OK] Audio: {f.name} ({size_mb:.2f} MB)")
            print(f"   [OK] En: {f}")
            return f

    print(f"   [X] No se encontro el archivo de audio")
    return None


def interactive_download():
    """Flujo interactivo para descargar video."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGADOR DE VIDEO (YouTube)")
    print("=" * 60)

    # Mostrar videos existentes
    existing = list(VIDEOS_DIR.glob("*.mp4")) if VIDEOS_DIR.exists() else []
    if existing:
        print(f"\n   Videos recientes:")
        for f in sorted(existing, key=lambda x: x.stat().st_mtime)[-5:]:
            size = f.stat().st_size / (1024 * 1024)
            print(f"     - {f.name} ({size:.2f} MB)")
        if len(existing) > 5:
            print(f"     ... y {len(existing) - 5} mas")

    # 1. Link
    print("\n--- PASO 1: Link del video ---")
    print("   (Shorts, videos normales, lo que sea de YouTube)")
    url = input("\n   Link: ").strip()
    if not url:
        print("   [X] No pusiste link. Saliendo.")
        return

    # 2. Con o sin audio?
    print("\n--- PASO 2: Audio ---")
    print("   1. Con audio    -> '{nombre} (audio).mp4' + '{nombre} (only audio).mp3'")
    print("   2. Sin audio    -> '{nombre} (sinaudio).mp4'")
    mode_choice = input("\n   Con o sin audio? (1/2): ").strip()
    include_audio = mode_choice != "2"

    # 3. Nombre
    print("\n--- PASO 3: Nombre ---")
    print("   (sin extension ni sufijo, ej: 'clip_epico')")
    name = input("   Nombre: ").strip()
    if not name:
        print("   [X] No pusiste nombre. Saliendo.")
        return

    # Construir filename
    if include_audio:
        video_filename = f"{name} (audio).mp4"
    else:
        video_filename = f"{name} (sinaudio).mp4"

    # 4. Descargar video
    print(f"\n--- PASO 4: Descargando ---")
    video_result = download_video(url, video_filename, include_audio)

    # 5. Audio por separado
    if include_audio and video_result:
        # SIEMPRE guarda audio aparte cuando se descarga con audio
        audio_filename = f"{name} (only audio).mp3"
        print(f"\n--- PASO 5: Guardando audio por separado ---")
        download_audio(url, audio_filename)

    elif not include_audio and video_result:
        # Si pidio sin audio, preguntar si quiere descargar el audio aparte
        print("\n--- PASO 5: Audio aparte ---")
        also_audio = input("   Descargar el audio por separado? (s/n): ").strip().lower()

        if also_audio == "s":
            print("\n   Nombre para el audio:")
            print("   (sin extension, ej: 'beat_epico')")
            audio_name = input("   Nombre audio: ").strip()
            if audio_name:
                audio_filename = f"{audio_name}.mp3"
            else:
                audio_filename = f"{name} (only audio).mp3"
            download_audio(url, audio_filename)

    # Resumen
    print(f"\n{'='*60}")
    print(f"   [OK] LISTO")
    print(f"{'='*60}")
    if video_result:
        print(f"   Video: {video_filename}")
        if include_audio:
            print(f"   Audio: {name} (only audio).mp3")
    print(f"   Carpeta videos: {VIDEOS_DIR}")
    print(f"   Carpeta audios: {AUDIOS_DIR}")
    print(f"{'='*60}")

    # Otro?
    otro = input("\n   Descargar otro video? (s/n): ").strip().lower()
    if otro == 's':
        interactive_download()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - Descargar video de YouTube")
    parser.add_argument("--url", type=str, default=None,
                        help="URL de YouTube")
    parser.add_argument("--name", type=str, default=None,
                        help="Nombre base (sin extension ni sufijo)")
    parser.add_argument("--mode", type=str, choices=["audio", "sinaudio"], default="audio",
                        help="'audio' = con audio, 'sinaudio' = sin audio")
    parser.add_argument("--also-audio", action="store_true",
                        help="Si mode=sinaudio, tambien descarga audio aparte")
    parser.add_argument("--audio-name", type=str, default=None,
                        help="Nombre para el audio aparte (sin extension)")
    args = parser.parse_args()

    if args.url and args.name:
        # Modo CLI directo
        include_audio = (args.mode == "audio")
        if include_audio:
            video_filename = f"{args.name} (audio).mp4"
        else:
            video_filename = f"{args.name} (sinaudio).mp4"

        video_result = download_video(args.url, video_filename, include_audio)

        # Si descargo con audio, SIEMPRE guardar audio aparte
        if include_audio and video_result:
            audio_filename = f"{args.name} (only audio).mp3"
            download_audio(args.url, audio_filename)

        # Si descargo sin audio y pidio also-audio
        if not include_audio and args.also_audio:
            audio_name = args.audio_name or args.name
            download_audio(args.url, f"{audio_name} (only audio).mp3")
    else:
        interactive_download()
