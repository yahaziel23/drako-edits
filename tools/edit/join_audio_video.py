#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Join Audio + Video

Junta un archivo de audio con un archivo de video.
La duracion del resultado es la del MAS CORTO:
  - Si el video dura menos que el audio → dura lo del video
  - Si el audio dura menos que el video → corta el video cuando acabe el audio

Reemplaza cualquier audio que ya tenga el video.
El resultado se guarda EN LA MISMA CARPETA de videos con "(joined)" en el nombre.

Uso:
    python tools/edit/join_audio_video.py

Dependencia: ffmpeg en PATH
"""

import sys
import io
import subprocess
from pathlib import Path
from datetime import timedelta

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

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def get_files_from_dir(directory, extensions):
    """Obtiene archivos de un directorio filtrados por extension."""
    if not directory.exists():
        return []
    files = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    return sorted(files)


def format_time(seconds):
    """Convierte segundos a formato legible."""
    if seconds is None:
        return "?"
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    ms = int((seconds - int(seconds)) * 1000)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"
    else:
        return f"{minutes:02d}:{secs:02d}.{ms:03d}"


def get_duration(file_path):
    """Obtiene la duracion de un archivo multimedia usando ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def join_audio_video(video_path, audio_path, output_path):
    """
    Junta audio + video. Duracion = min(video, audio).
    Reemplaza audio existente del video.
    """
    video_dur = get_duration(video_path)
    audio_dur = get_duration(audio_path)

    if video_dur is None:
        print("   [X] No se pudo leer duracion del video.")
        return False
    if audio_dur is None:
        print("   [X] No se pudo leer duracion del audio.")
        return False

    final_dur = min(video_dur, audio_dur)
    shorter = "video" if video_dur <= audio_dur else "audio"

    print(f"   Video: {format_time(video_dur)} ({video_dur:.2f}s)")
    print(f"   Audio: {format_time(audio_dur)} ({audio_dur:.2f}s)")
    print(f"   Resultado: {format_time(final_dur)} (limitado por {shorter})")

    # ffmpeg: reemplaza audio del video, corta al mas corto
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-t", str(final_dur),
        "-shortest",
        str(output_path)
    ]

    print("\n   Procesando...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"   [OK] Guardado: {output_path.name} ({size_mb:.2f} MB)")
        return True

    # Fallback: re-encode video tambien
    print("   [!] Copy fallo, re-encoding...")
    output_path.unlink(missing_ok=True)

    cmd_reencode = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-t", str(final_dur),
        str(output_path)
    ]

    result = subprocess.run(cmd_reencode, capture_output=True, text=True)

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"   [OK] Guardado (re-encode): {output_path.name} ({size_mb:.2f} MB)")
        return True

    print(f"   [X] Error ffmpeg: {result.stderr[-300:]}")
    return False


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def interactive_join():
    """Flujo interactivo para juntar audio + video."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - JOIN AUDIO + VIDEO")
    print("=" * 60)
    print("   Junta un audio con un video.")
    print("   Duracion = lo que dure MENOS (audio o video).")
    print("   Reemplaza el audio original del video.")
    print("=" * 60)

    # 1. Seleccionar video
    print(f"\n   Carpeta videos: {VIDEOS_DIR}")
    videos = get_files_from_dir(VIDEOS_DIR, VIDEO_EXTENSIONS)

    if not videos:
        print(f"\n   [X] No hay videos en {VIDEOS_DIR}")
        print(f"       Primero descarga algo con tools/youtube/download_video_yt.py")
        return

    print("\n--- PASO 1: Selecciona el VIDEO ---")
    for i, v in enumerate(videos, 1):
        duration = get_duration(v)
        dur_str = f" ({format_time(duration)})" if duration else ""
        size_mb = v.stat().st_size / (1024 * 1024)
        print(f"      {i}. {v.name}{dur_str} [{size_mb:.1f} MB]")

    while True:
        choice = input("\n   Video (numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(videos):
                video_path = videos[idx]
                break
        print("   [!] No valido.")

    # 2. Seleccionar audio
    print(f"\n   Carpeta audios: {AUDIOS_DIR}")
    audios = get_files_from_dir(AUDIOS_DIR, AUDIO_EXTENSIONS)

    if not audios:
        print(f"\n   [X] No hay audios en {AUDIOS_DIR}")
        print(f"       Descarga audio con tools/youtube/download_audio_yt.py")
        return

    print("\n--- PASO 2: Selecciona el AUDIO ---")
    for i, a in enumerate(audios, 1):
        duration = get_duration(a)
        dur_str = f" ({format_time(duration)})" if duration else ""
        size_mb = a.stat().st_size / (1024 * 1024)
        print(f"      {i}. {a.name}{dur_str} [{size_mb:.1f} MB]")

    while True:
        choice = input("\n   Audio (numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(audios):
                audio_path = audios[idx]
                break
        print("   [!] No valido.")

    # 3. Nombre de salida
    print("\n--- PASO 3: Nombre del resultado ---")
    default_name = f"{video_path.stem} (joined)"
    print(f"   Default: {default_name}.mp4")
    custom = input("   Nombre (Enter = default): ").strip()

    if custom:
        output_name = f"{custom}.mp4"
    else:
        output_name = f"{default_name}.mp4"

    output_path = VIDEOS_DIR / output_name

    # 4. Confirmar
    print(f"\n--- RESUMEN ---")
    print(f"   Video: {video_path.name}")
    print(f"   Audio: {audio_path.name}")
    print(f"   Output: {output_name}")
    confirm = input("\n   Continuar? (Enter=si, n=cancelar): ").strip().lower()
    if confirm == 'n':
        print("   Cancelado.")
        return

    # 5. Ejecutar
    print(f"\n--- PROCESANDO ---")
    success = join_audio_video(video_path, audio_path, output_path)

    if success:
        print(f"\n{'='*60}")
        print(f"   [OK] LISTO")
        print(f"   Resultado: {output_path}")
        print(f"{'='*60}")
    else:
        print(f"\n   [X] Fallo el join. Revisa que ffmpeg este en PATH.")

    # Otro?
    otro = input("\n   Juntar otro? (s/n): ").strip().lower()
    if otro == 's':
        interactive_join()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    interactive_join()
