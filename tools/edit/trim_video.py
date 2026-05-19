#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Trim Video

Recorta videos de tools_output/videos/.
El resultado se guarda EN LA MISMA CARPETA con "(trim)" en el nombre.

Flujo:
    1. Te muestra los videos disponibles en tools_output/videos/
    2. Seleccionas uno
    3. Te dice cuanto dura
    4. Te pide tiempo inicial (desde donde cortar)
    5. Te pregunta tiempo final:
       - Hasta el final del video (max)
       - O un tiempo especifico
    6. Se guarda como "{nombre} (trim).mp4"

FIX para clips cortos (< 2s):
    Usa re-encode forzado con preset ultrafast para evitar archivos de 0KB.

Uso:
    python tools/edit/trim_video.py
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

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv'}

# Duracion minima para intentar stream copy (debajo de esto siempre re-encode)
MIN_DURATION_FOR_COPY = 2.0  # segundos


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


def parse_time_input(time_str):
    """
    Parsea input de tiempo flexible. Acepta:
        - Segundos: "30", "1.5", "0.8"
        - MM:SS: "1:30", "01:30.5"
        - HH:MM:SS: "1:05:30"
    Retorna segundos como float.
    """
    time_str = time_str.strip()
    parts = time_str.split(":")

    try:
        if len(parts) == 1:
            return float(parts[0])
        elif len(parts) == 2:
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        elif len(parts) == 3:
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

    # Fallback con moviepy
    try:
        from moviepy import VideoFileClip
        clip = VideoFileClip(str(video_path))
        dur = clip.duration
        clip.close()
        return dur
    except Exception:
        return None


def trim_with_ffmpeg(input_path, output_path, start, end):
    """
    Recorta video usando ffmpeg.
    
    Para clips cortos (< 2s): siempre re-encode para evitar 0KB.
    Para clips normales: intenta copy primero, luego re-encode si falla.
    """
    trim_duration = end - start

    # === CLIPS CORTOS: forzar re-encode ===
    if trim_duration < MIN_DURATION_FOR_COPY:
        print(f"   [!] Clip corto ({trim_duration:.2f}s) - usando re-encode forzado...")
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(input_path),
            "-t", str(trim_duration),
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "18",
            "-force_key_frames", "expr:gte(t,0)",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            if output_path.exists() and output_path.stat().st_size > 1000:
                return True, "re-encode (clip corto)"
            else:
                print(f"   [X] Archivo invalido ({output_path.stat().st_size} bytes)")
                output_path.unlink(missing_ok=True)
                cmd.remove("-shortest")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
                    return True, "re-encode (retry)"

        print(f"   [X] Error: {result.stderr[-300:]}")
        return False, None

    # === CLIPS NORMALES: intentar copy primero ===
    print("   Intentando recorte rapido (sin re-encoding)...")
    cmd_copy = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-ss", str(start),
        "-t", str(trim_duration),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output_path)
    ]

    result = subprocess.run(cmd_copy, capture_output=True, text=True)

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
        out_dur = get_video_duration(output_path)
        if out_dur and abs(out_dur - trim_duration) < 1.0:
            return True, "copy"
        else:
            print(f"   [!] Copy impreciso, re-encoding...")
            output_path.unlink(missing_ok=True)

    # Fallback: re-encode
    print("   Re-encoding para precision exacta...")
    cmd_encode = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_path),
        "-t", str(trim_duration),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        str(output_path)
    ]

    result = subprocess.run(cmd_encode, capture_output=True, text=True)

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
        return True, "re-encode"

    print(f"   [X] Error ffmpeg: {result.stderr[-300:]}")
    return False, None


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def interactive_trim():
    """Flujo interactivo para recortar video."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - TRIM VIDEO")
    print("=" * 60)
    print(f"   Carpeta: {VIDEOS_DIR}")

    # Verificar carpeta
    if not VIDEOS_DIR.exists():
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\n   [!] No hay videos en tools_output/videos/")
        print(f"       Primero descarga algo con tools/youtube/download_video_yt.py")
        return

    # 1. Listar videos
    videos = get_videos_from_dir(VIDEOS_DIR)
    if not videos:
        print(f"\n   [X] No hay videos en {VIDEOS_DIR}")
        print(f"       Primero descarga algo con tools/youtube/download_video_yt.py")
        return

    print("\n   Videos disponibles:")
    for i, v in enumerate(videos, 1):
        duration = get_video_duration(v)
        dur_str = f" ({format_time(duration)})" if duration else ""
        size_mb = v.stat().st_size / (1024 * 1024)
        print(f"      {i}. {v.name}{dur_str} [{size_mb:.1f} MB]")

    # 2. Seleccionar
    while True:
        choice = input("\n   Video (numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(videos):
                video_path = videos[idx]
                break
        print("   [!] No valido.")

    # 3. Mostrar duracion
    duration = get_video_duration(video_path)
    if duration is None:
        print("   [X] No se pudo leer la duracion.")
        return

    print(f"\n   Video: {video_path.name}")
    print(f"   Duracion total: {format_time(duration)} ({duration:.2f}s)")

    # 4. Tiempo inicial
    print("\n--- Tiempo inicial ---")
    print("   Formatos: segundos (5.5), MM:SS (1:30), HH:MM:SS")
    while True:
        start_input = input("\n   Desde (tiempo): ").strip()
        start = parse_time_input(start_input)
        if start is None:
            print("   [!] Formato no valido.")
            continue
        if start < 0:
            print("   [!] No puede ser negativo.")
            continue
        if start >= duration:
            print(f"   [!] Excede la duracion ({format_time(duration)}).")
            continue
        break

    remaining = duration - start
    print(f"   -> Inicio: {format_time(start)}")
    print(f"   -> Tiempo restante: {format_time(remaining)} ({remaining:.2f}s)")

    # 5. Tiempo final
    print("\n--- Tiempo final ---")
    print(f"   1. Hasta el final ({format_time(duration)})")
    print(f"   2. Tiempo especifico")

    while True:
        mode = input("\n   Opcion (1/2): ").strip()

        if mode == "1":
            end = duration
            break
        elif mode == "2":
            print(f"\n   Maximo posible: {format_time(duration)} ({duration:.2f}s)")
            while True:
                end_input = input(f"   Hasta (tiempo): ").strip()
                end = parse_time_input(end_input)
                if end is None:
                    print("   [!] Formato no valido.")
                    continue
                if end <= start:
                    print(f"   [!] Debe ser mayor al inicio ({format_time(start)}).")
                    continue
                if end > duration:
                    print(f"   [!] Excede la duracion. Usando {format_time(duration)}.")
                    end = duration
                break
            break
        else:
            print("   [!] Elige 1 o 2.")

    trim_duration = end - start
    print(f"\n   Resumen del recorte:")
    print(f"     Desde: {format_time(start)}")
    print(f"     Hasta: {format_time(end)}")
    print(f"     Duracion: {format_time(trim_duration)} ({trim_duration:.2f}s)")

    # 6. Nombre
    base_name = video_path.stem
    for suffix in ["(trim)", "(audio)", "(sinaudio)", "(clean)"]:
        base_name = base_name.replace(suffix, "").strip()

    output_name = f"{base_name} (trim).mp4"
    print(f"\n   Se guardara como: {output_name}")

    custom = input("   Cambiar nombre? (Enter=no, o escribe nuevo): ").strip()
    if custom:
        if not custom.endswith(".mp4"):
            custom += ".mp4"
        output_name = custom

    output_path = VIDEOS_DIR / output_name

    # 7. Recortar
    print(f"\n{'='*60}")
    print(f"   RECORTANDO...")
    print(f"{'='*60}")

    success, method = trim_with_ffmpeg(video_path, output_path, start, end)

    if success:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        out_dur = get_video_duration(output_path)
        print(f"\n   [OK] Listo! (metodo: {method})")
        print(f"   Archivo: {output_name}")
        print(f"   Duracion real: {format_time(out_dur)}")
        print(f"   Tamano: {size_mb:.2f} MB")
        print(f"   En: {output_path}")
    else:
        print(f"\n   [X] Error al recortar el video.")

    # Otro recorte?
    otro = input("\n   Otro recorte? (s/n): ").strip().lower()
    if otro == "s":
        interactive_trim()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    interactive_trim()
