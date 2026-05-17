#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Recortador de Videos

Recorta videos eligiendo punto de inicio y final.
Soporta 3 modos de recorte:
    1. Desde un punto hasta el final del video
    2. Desde un punto + duracion especifica (X segundos)
    3. Desde un punto hasta otro punto especifico

Uso:
    python trim_video.py

Preparar antes:
    - Colocar videos en assets/trim/videos/
    - El resultado se guarda en output/trim/
"""

import sys
import io
import os
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

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "trim"
VIDEOS_DIR = ASSETS_DIR / "videos"
OUTPUT_DIR = SCRIPT_DIR / "output" / "trim"

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv'}


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def get_videos_from_dir(directory):
    """Obtiene todos los videos de un directorio."""
    if not directory.exists():
        return []
    vids = [f for f in directory.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS]
    return sorted(vids)


def format_time(seconds):
    """Convierte segundos a formato legible HH:MM:SS.ms"""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    ms = int((seconds - int(seconds)) * 100)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}.{ms:02d}"


def parse_time_input(time_str):
    """
    Parsea input de tiempo flexible. Acepta:
        - Segundos: "30", "90.5"
        - MM:SS: "1:30", "01:30.5"
        - HH:MM:SS: "1:05:30", "01:05:30.5"
    Retorna segundos como float.
    """
    time_str = time_str.strip()

    parts = time_str.split(":")
    try:
        if len(parts) == 1:
            # Solo segundos
            return float(parts[0])
        elif len(parts) == 2:
            # MM:SS
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        elif len(parts) == 3:
            # HH:MM:SS
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        else:
            return None
    except ValueError:
        return None


def get_video_duration(video_path):
    """Obtiene la duracion del video usando ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # Fallback: moviepy (mas lento pero siempre funciona)
    try:
        from moviepy import VideoFileClip
        clip = VideoFileClip(str(video_path))
        dur = clip.duration
        clip.close()
        return dur
    except Exception:
        return None


def trim_with_ffmpeg(input_path, output_path, start, end=None, duration=None):
    """
    Recorta video usando ffmpeg con stream copy (rapido, sin re-encoding).
    Si falla con copy, reintenta con re-encoding.
    """
    # Construir comando base
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_path),
    ]

    if duration is not None:
        cmd += ["-t", str(duration)]
    elif end is not None:
        cmd += ["-t", str(end - start)]

    # Intentar primero con copy (rapido)
    cmd_copy = cmd + ["-c", "copy", "-avoid_negative_ts", "make_zero", str(output_path)]

    print("   Intentando recorte rapido (sin re-encoding)...")
    result = subprocess.run(cmd_copy, capture_output=True, text=True)

    if result.returncode == 0:
        return True, "copy"

    # Si fallo, reintentar con re-encoding
    print("   Re-encoding necesario (puede tardar mas)...")
    cmd_encode = cmd + [
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path)
    ]

    result = subprocess.run(cmd_encode, capture_output=True, text=True)

    if result.returncode == 0:
        return True, "re-encode"

    print(f"   [X] Error ffmpeg: {result.stderr[-200:]}")
    return False, None


# =============================================================================
# SELECCION INTERACTIVA
# =============================================================================

def select_video():
    """Muestra videos disponibles y deja elegir."""
    videos = get_videos_from_dir(VIDEOS_DIR)
    if not videos:
        print(f"\n   [X] No hay videos en {VIDEOS_DIR}")
        print(f"       Coloca tus videos ahi y vuelve a correr el script.")
        sys.exit(1)

    print("\n   Videos disponibles:")
    for i, v in enumerate(videos, 1):
        duration = get_video_duration(v)
        dur_str = f" ({format_time(duration)})" if duration else ""
        print(f"      {i}. {v.name}{dur_str}")

    while True:
        choice = input("\n   Video a recortar (numero o nombre): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(videos):
                return videos[idx]
        else:
            for v in videos:
                if v.stem.lower() == choice.lower() or v.name.lower() == choice.lower():
                    return v
        print("   [!] No valido, intenta de nuevo.")


def select_start_time(duration):
    """Pide el segundo de inicio del recorte."""
    print(f"\n   Duracion total del video: {format_time(duration)}")
    print(f"   Formatos aceptados: segundos (30), MM:SS (1:30), HH:MM:SS (1:05:30)")

    while True:
        time_input = input("\n   Segundo de inicio del recorte: ").strip()

        if not time_input:
            print("   [!] Debes ingresar un tiempo.")
            continue

        seconds = parse_time_input(time_input)

        if seconds is None:
            print("   [!] Formato no valido.")
            continue

        if seconds < 0:
            print("   [!] El tiempo no puede ser negativo.")
            continue

        if seconds >= duration:
            print(f"   [!] El inicio ({format_time(seconds)}) excede la duracion ({format_time(duration)}).")
            continue

        print(f"   -> Inicio: {format_time(seconds)}")
        return seconds


def select_trim_mode(start, duration):
    """Muestra las 3 opciones de recorte y retorna (end, trim_duration)."""
    remaining = duration - start

    print(f"\n   Tiempo restante desde {format_time(start)}: {format_time(remaining)}")
    print(f"\n   Como quieres recortar?")
    print(f"      1. Hasta el final del video")
    print(f"      2. Duracion especifica (recortar X segundos desde el inicio)")
    print(f"      3. Hasta un segundo especifico del video")

    while True:
        mode = input("\n   Opcion (1/2/3): ").strip()

        if mode == "1":
            # Hasta el final
            print(f"   -> Recorte: {format_time(start)} hasta {format_time(duration)} ({format_time(remaining)})")
            return duration, None

        elif mode == "2":
            # Duracion especifica
            while True:
                dur_input = input(f"\n   Duracion del recorte (max {format_time(remaining)}): ").strip()
                trim_dur = parse_time_input(dur_input)

                if trim_dur is None:
                    print("   [!] Formato no valido.")
                    continue
                if trim_dur <= 0:
                    print("   [!] La duracion debe ser mayor a 0.")
                    continue
                if trim_dur > remaining:
                    print(f"   [!] Excede el tiempo restante ({format_time(remaining)}).")
                    continue

                end = start + trim_dur
                print(f"   -> Recorte: {format_time(start)} hasta {format_time(end)} (duracion: {format_time(trim_dur)})")
                return end, trim_dur

        elif mode == "3":
            # Hasta un segundo especifico
            while True:
                end_input = input(f"\n   Segundo final (entre {format_time(start)} y {format_time(duration)}): ").strip()
                end_sec = parse_time_input(end_input)

                if end_sec is None:
                    print("   [!] Formato no valido.")
                    continue
                if end_sec <= start:
                    print(f"   [!] El final debe ser mayor al inicio ({format_time(start)}).")
                    continue
                if end_sec > duration:
                    print(f"   [!] Excede la duracion del video ({format_time(duration)}).")
                    continue

                trim_dur = end_sec - start
                print(f"   -> Recorte: {format_time(start)} hasta {format_time(end_sec)} (duracion: {format_time(trim_dur)})")
                return end_sec, trim_dur

        else:
            print("   [!] Opcion no valida. Elige 1, 2 o 3.")


# =============================================================================
# GENERADOR
# =============================================================================

def trim_video(video_path, start, end, trim_duration, output_name=None):
    """Ejecuta el recorte del video."""
    print(f"\n{'='*50}")
    print(f"   RECORTANDO VIDEO")
    print(f"   Video: {video_path.name}")
    print(f"   Desde: {format_time(start)}")
    print(f"   Hasta: {format_time(end)}")
    print(f"   Duracion del recorte: {format_time(end - start)}")
    print(f"{'='*50}")

    # Nombre de salida
    if output_name is None:
        start_str = format_time(start).replace(":", "").replace(".", "")
        end_str = format_time(end).replace(":", "").replace(".", "")
        output_name = f"{video_path.stem}_trim_{start_str}_{end_str}"

    output_path = OUTPUT_DIR / f"{output_name}{video_path.suffix}"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Ejecutar recorte
    print("\n   Procesando...")
    success, method = trim_with_ffmpeg(video_path, output_path, start, end=end)

    if success:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"\n   [OK] Listo! ({method})")
        print(f"   Archivo: {output_path.name}")
        print(f"   Tamano: {size_mb:.1f} MB")
        print(f"   Ruta: {output_path}")
        return output_path
    else:
        print(f"\n   [X] Error al recortar el video.")
        return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 50)
    print("   DRAKO EDITS - Trim Video")
    print("=" * 50)

    # Verificar carpeta
    if not VIDEOS_DIR.exists():
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\n   [!] Se creo la carpeta: {VIDEOS_DIR}")
        print(f"       Coloca tus videos ahi y vuelve a correr el script.")
        sys.exit(0)

    # 1. Seleccionar video
    video_path = select_video()
    print(f"\n   -> Video seleccionado: {video_path.name}")

    # 2. Obtener duracion
    duration = get_video_duration(video_path)
    if duration is None:
        print(f"\n   [X] No se pudo leer la duracion del video.")
        sys.exit(1)

    # 3. Segundo de inicio
    start = select_start_time(duration)

    # 4. Modo de recorte (3 opciones)
    end, trim_dur = select_trim_mode(start, duration)

    # 5. Nombre de salida (opcional)
    output_name = input("\n   Nombre del archivo (sin extension, Enter=auto): ").strip()
    if not output_name:
        output_name = None

    # 6. Recortar
    trim_video(video_path, start, end, trim_dur, output_name)

    # Preguntar si quiere otro recorte del mismo video
    while True:
        again = input("\n   Otro recorte del mismo video? (s/n): ").strip().lower()
        if again in ("s", "si", "y", "yes"):
            start = select_start_time(duration)
            end, trim_dur = select_trim_mode(start, duration)
            output_name = input("\n   Nombre del archivo (sin extension, Enter=auto): ").strip()
            if not output_name:
                output_name = None
            trim_video(video_path, start, end, trim_dur, output_name)
        else:
            break

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
