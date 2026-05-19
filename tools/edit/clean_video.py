#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Clean Video (quitar barras negras)

Detecta y remueve franjas negras (letterboxing) de videos.
Muchos videos de reacciones tienen barras negras arriba y abajo.
Este script las detecta automaticamente y exporta el video
con el tamano real del contenido (sin las barras).

Como funciona:
    1. Analiza los primeros frames del video
    2. Detecta filas de pixeles "negros" (luminosidad < threshold)
    3. Calcula el crop exacto (top + bottom)
    4. Exporta el video recortado con ffmpeg (rapido, sin re-encode)

Output: Se guarda en la misma carpeta con "(clean)" en el nombre.

Uso:
    python tools/edit/clean_video.py
"""

import sys
import io
import subprocess
import json
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

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv'}

# Deteccion de barras negras
BLACK_THRESHOLD = 20        # Luminosidad maxima para considerar "negro" (0-255)
MIN_BAR_PIXELS = 10         # Minimo de pixeles de barra para considerar valido
SAMPLE_FRAMES = 5           # Cuantos frames analizar (mas = mas preciso pero mas lento)


# =============================================================================
# FUNCIONES
# =============================================================================

def get_videos_from_dir(directory):
    """Obtiene todos los videos de un directorio."""
    if not directory.exists():
        return []
    vids = [f for f in directory.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS]
    return sorted(vids)


def get_video_info(video_path):
    """Obtiene informacion del video (duracion, ancho, alto)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(video_path)
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream["width"])
                    height = int(stream["height"])
                    duration = float(data.get("format", {}).get("duration", 0))
                    return {"width": width, "height": height, "duration": duration}
    except Exception:
        pass
    return None


def detect_crop_with_ffmpeg(video_path, duration):
    """
    Usa ffmpeg cropdetect para detectar barras negras automaticamente.
    Retorna: (crop_width, crop_height, crop_x, crop_y) o None
    """
    analyze_points = []
    if duration > 2:
        for pct in [0.2, 0.4, 0.6]:
            analyze_points.append(duration * pct)
    else:
        analyze_points.append(0.5)

    crops_detected = []

    for seek_time in analyze_points:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(seek_time),
            "-i", str(video_path),
            "-vframes", "10",
            "-vf", f"cropdetect=limit={BLACK_THRESHOLD}:round=2:reset=0",
            "-f", "null",
            "-"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        import re
        for line in result.stderr.split("\n"):
            match = re.search(r"crop=(\d+):(\d+):(\d+):(\d+)", line)
            if match:
                crop_w = int(match.group(1))
                crop_h = int(match.group(2))
                crop_x = int(match.group(3))
                crop_y = int(match.group(4))
                crops_detected.append((crop_w, crop_h, crop_x, crop_y))

    if not crops_detected:
        return None

    from collections import Counter
    crop_counter = Counter(crops_detected)
    most_common = crop_counter.most_common(1)[0][0]
    return most_common


def clean_video_ffmpeg(input_path, output_path, crop_w, crop_h, crop_x, crop_y):
    """Aplica el crop al video usando ffmpeg."""
    crop_filter = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", crop_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-c:a", "copy",
        str(output_path)
    ]

    print(f"   Aplicando crop: {crop_filter}")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000:
        return True

    print(f"   [X] Error: {result.stderr[-200:]}")
    return False


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def interactive_clean():
    """Flujo interactivo para limpiar barras negras."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - CLEAN VIDEO (quitar barras negras)")
    print("=" * 60)
    print(f"   Carpeta: {VIDEOS_DIR}")

    if not VIDEOS_DIR.exists():
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"\n   [X] No hay videos en tools_output/videos/")
        return

    videos = get_videos_from_dir(VIDEOS_DIR)
    if not videos:
        print(f"\n   [X] No hay videos en {VIDEOS_DIR}")
        return

    print("\n   Videos disponibles:")
    for i, v in enumerate(videos, 1):
        info = get_video_info(v)
        if info:
            size_mb = v.stat().st_size / (1024 * 1024)
            print(f"      {i}. {v.name} ({info['width']}x{info['height']}) [{size_mb:.1f} MB]")
        else:
            print(f"      {i}. {v.name}")

    while True:
        choice = input("\n   Video (numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(videos):
                video_path = videos[idx]
                break
        print("   [!] No valido.")

    info = get_video_info(video_path)
    if not info:
        print("   [X] No se pudo leer info del video.")
        return

    print(f"\n   Video: {video_path.name}")
    print(f"   Tamano original: {info['width']}x{info['height']}")
    print(f"   Duracion: {info['duration']:.2f}s")

    print("\n   Analizando barras negras...")
    crop = detect_crop_with_ffmpeg(video_path, info['duration'])

    if crop is None:
        print("   [!] No se detectaron barras negras en este video.")
        return

    crop_w, crop_h, crop_x, crop_y = crop

    if crop_w == info['width'] and crop_h == info['height']:
        print("   [OK] No se detectaron barras negras. El video ya esta limpio.")
        return

    top_bar = crop_y
    bottom_bar = info['height'] - (crop_y + crop_h)
    total_removed = top_bar + bottom_bar

    print(f"\n   [DETECTADO] Barras negras:")
    print(f"     Arriba:  {top_bar}px")
    print(f"     Abajo:   {bottom_bar}px")
    print(f"     Total a remover: {total_removed}px")
    print(f"     Tamano final: {crop_w}x{crop_h} (antes: {info['width']}x{info['height']})")

    confirm = input("\n   Aplicar limpieza? (s/n): ").strip().lower()
    if confirm != "s":
        print("   Cancelado.")
        return

    base_name = video_path.stem
    for suffix in ["(trim)", "(audio)", "(sinaudio)", "(clean)"]:
        base_name = base_name.replace(suffix, "").strip()

    output_name = f"{base_name} (clean).mp4"
    output_path = VIDEOS_DIR / output_name

    print(f"\n{'='*60}")
    print(f"   LIMPIANDO VIDEO...")
    print(f"{'='*60}")

    success = clean_video_ffmpeg(video_path, output_path, crop_w, crop_h, crop_x, crop_y)

    if success:
        size_mb = output_path.stat().st_size / (1024 * 1024)
        new_info = get_video_info(output_path)
        print(f"\n   [OK] Listo!")
        print(f"   Archivo: {output_name}")
        if new_info:
            print(f"   Tamano: {new_info['width']}x{new_info['height']} (era {info['width']}x{info['height']})")
        print(f"   Peso: {size_mb:.2f} MB")
        print(f"   En: {output_path}")
    else:
        print(f"\n   [X] Error al limpiar el video.")

    otro = input("\n   Limpiar otro video? (s/n): ").strip().lower()
    if otro == "s":
        interactive_clean()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    interactive_clean()
