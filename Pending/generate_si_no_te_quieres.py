#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador Bulk: "Si no te quieres bañar"

Genera videos del meme en masa usando imagenes pre-curadas por beat.
Cada video es una combinacion unica de imagenes + subtitulos.

Uso:
    python generate_si_no_te_quieres.py
    python generate_si_no_te_quieres.py --num 20

Estructura requerida:
    assets/si_no_te_quieres_banar/
        audio/audio_meme.mp3
        beat_1/   (imagenes reaccion)
        beat_2/   (imagenes "A NO")
        beat_3/   (imagenes "de color")
"""

import os
import sys
import random
import argparse
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, CompositeVideoClip


# =============================================================================
# CONFIGURACION
# =============================================================================

# Ruta base (relativa al script)
SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "si_no_te_quieres_banar"

AUDIO_PATH = ASSETS_DIR / "audio" / "audio_meme.mp3"
BEAT_1_DIR = ASSETS_DIR / "beat_1"
BEAT_2_DIR = ASSETS_DIR / "beat_2"
BEAT_3_DIR = ASSETS_DIR / "beat_3"
OUTPUT_DIR = SCRIPT_DIR / "output" / "si_no_te_quieres_banar"

# Timestamps confirmados (Audacity)
BEATS = [
    {"name": "beat_1", "start": 0.000, "end": 2.676, "text": "Si no te quieres bañar", "style": "centered"},
    {"name": "beat_2", "start": 2.676, "end": 3.968, "text": "A NO", "style": "random"},
    {"name": "beat_3", "start": 3.968, "end": 5.652, "text": "De color vas a cambiar...", "style": "centered"},
]

# Duracion total del video (fin del ultimo beat)
TOTAL_DURATION = BEATS[-1]["end"]  # 5.652s

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Subtitle config
FONT_SIZE = 90
STROKE_WIDTH = 5
SUBTITLE_Y = int(VIDEO_HEIGHT * 0.55)


# =============================================================================
# FUNCIONES
# =============================================================================

def get_images_from_dir(directory):
    """Obtiene todas las imagenes de un directorio."""
    extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    imgs = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    return sorted(imgs)


def resize_to_vertical(img_path):
    """Redimensiona y cropea cualquier imagen a 1080x1920."""
    img = Image.open(img_path).convert("RGB")
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        new_h = VIDEO_HEIGHT
        new_w = int(new_h * img_ratio)
    else:
        new_w = VIDEO_WIDTH
        new_h = int(new_w / img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - VIDEO_WIDTH) // 2
    top = (new_h - VIDEO_HEIGHT) // 2
    return img.crop((left, top, left + VIDEO_WIDTH, top + VIDEO_HEIGHT))


def find_font():
    """Busca una fuente bold disponible en el sistema."""
    font_paths = [
        # Windows
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/IMPACT.TTF",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/ARIALBD.TTF",
        # Linux
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        # Mac
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for p in font_paths:
        if Path(p).exists():
            return p
    return None


def render_subtitle_centered(text, font_path):
    """
    Renderiza subtitulo centrado con stroke negro.
    Retorna: numpy array RGBA.
    """
    try:
        font = ImageFont.truetype(font_path, FONT_SIZE) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=STROKE_WIDTH)
    tw = bbox[2] - bbox[0] + STROKE_WIDTH * 2 + 20
    th = bbox[3] - bbox[1] + STROKE_WIDTH * 2 + 20

    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = -bbox[0] + STROKE_WIDTH + 10
    y = -bbox[1] + STROKE_WIDTH + 10
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255),
              stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255))

    return np.array(img)


def render_subtitle_random(text, font_path):
    """
    Renderiza subtitulo 'A NO' con posicion/rotacion aleatoria.
    Siempre blanco, un poco mas grande que los demas, posicion y rotacion random.
    Retorna: (numpy array RGBA, x_pos, y_pos)
    """
    # Un poco mas grande que los otros (entre 100 y 115)
    big_font_size = FONT_SIZE + random.randint(10, 25)
    try:
        font = ImageFont.truetype(font_path, big_font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=STROKE_WIDTH + 2)
    tw = bbox[2] - bbox[0] + STROKE_WIDTH * 2 + 40
    th = bbox[3] - bbox[1] + STROKE_WIDTH * 2 + 40

    img = Image.new("RGBA", (tw + 100, th + 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = -bbox[0] + STROKE_WIDTH + 50
    y = -bbox[1] + STROKE_WIDTH + 50

    # Siempre blanco
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255),
              stroke_width=STROKE_WIDTH + 2, stroke_fill=(0, 0, 0, 255))

    # Rotacion aleatoria (-25 a 25 grados)
    rotation = random.randint(-25, 25)
    img = img.rotate(rotation, expand=True, resample=Image.BICUBIC)

    # Posicion aleatoria (dentro de pantalla)
    max_x = max(0, VIDEO_WIDTH - img.width)
    max_y_top = int(VIDEO_HEIGHT * 0.30)
    max_y_bottom = int(VIDEO_HEIGHT * 0.65)
    x_pos = random.randint(0, max(1, max_x))
    y_pos = random.randint(max_y_top, max_y_bottom)

    return np.array(img), x_pos, y_pos


# =============================================================================
# GENERADOR
# =============================================================================

def generate_video(video_num, beat_1_imgs, beat_2_imgs, beat_3_imgs, font_path):
    """Genera un video del meme con imagenes random de cada beat."""
    print(f"\n{'='*50}")
    print(f"   VIDEO {video_num}")
    print(f"{'='*50}")

    # 1. Seleccionar imagenes random
    img1_path = random.choice(beat_1_imgs)
    img2_path = random.choice(beat_2_imgs)
    img3_path = random.choice(beat_3_imgs)
    print(f"   Beat 1: {img1_path.name}")
    print(f"   Beat 2: {img2_path.name}")
    print(f"   Beat 3: {img3_path.name}")

    # 2. Redimensionar imagenes a vertical
    img1 = resize_to_vertical(img1_path)
    img2 = resize_to_vertical(img2_path)
    img3 = resize_to_vertical(img3_path)

    # 3. Cargar audio y cortar a la duracion exacta
    audio_clip = AudioFileClip(str(AUDIO_PATH)).subclipped(0, TOTAL_DURATION)

    # 4. Crear clips de imagen por beat
    image_clips = []
    images = [img1, img2, img3]

    for i, beat in enumerate(BEATS):
        start = beat["start"]
        dur = beat["end"] - beat["start"]
        img_array = np.array(images[i])
        clip = ImageClip(img_array).with_start(start).with_duration(dur)
        image_clips.append(clip)

    # 5. Crear subtitulos
    subtitle_clips = []

    for beat in BEATS:
        start = beat["start"]
        dur = beat["end"] - beat["start"]
        text = beat["text"]
        style = beat["style"]

        if style == "centered":
            sub_img = render_subtitle_centered(text, font_path)
            x_pos = max(0, (VIDEO_WIDTH - sub_img.shape[1]) // 2)
            y_pos = SUBTITLE_Y
            clip = ImageClip(sub_img, transparent=True)
            clip = clip.with_position((x_pos, y_pos)).with_start(start).with_duration(dur)
            subtitle_clips.append(clip)

        elif style == "random":
            sub_img, x_pos, y_pos = render_subtitle_random(text, font_path)
            clip = ImageClip(sub_img, transparent=True)
            clip = clip.with_position((x_pos, y_pos)).with_start(start).with_duration(dur)
            subtitle_clips.append(clip)

    # 6. Componer video final
    all_clips = image_clips + subtitle_clips
    final = CompositeVideoClip(all_clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(TOTAL_DURATION).with_audio(audio_clip)

    # 7. Export
    output_path = OUTPUT_DIR / f"video_{video_num:03d}.mp4"
    print(f"   Renderizando...")

    final.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="fast",
        threads=4,
        logger=None
    )

    final.close()
    audio_clip.close()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"   ✅ Listo: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


def generate_bulk(num_videos=10):
    """Genera N videos en batch."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - BULK GENERATOR")
    print("   Meme: Si no te quieres bañar")
    print("=" * 60)

    # Crear output dir
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Verificar assets
    if not AUDIO_PATH.exists():
        print(f"\n   ❌ ERROR: Audio no encontrado en {AUDIO_PATH}")
        print(f"   Coloca el audio en: assets/si_no_te_quieres_banar/audio/audio_meme.mp3")
        sys.exit(1)

    beat_1_imgs = get_images_from_dir(BEAT_1_DIR)
    beat_2_imgs = get_images_from_dir(BEAT_2_DIR)
    beat_3_imgs = get_images_from_dir(BEAT_3_DIR)

    print(f"\n   Imagenes disponibles:")
    print(f"     Beat 1 (reaccion):  {len(beat_1_imgs)}")
    print(f"     Beat 2 (A NO):      {len(beat_2_imgs)}")
    print(f"     Beat 3 (de color):  {len(beat_3_imgs)}")
    print(f"   Combinaciones posibles: {len(beat_1_imgs) * len(beat_2_imgs) * len(beat_3_imgs):,}")
    print(f"   Videos a generar: {num_videos}")

    if not beat_1_imgs:
        print(f"\n   ❌ ERROR: No hay imagenes en {BEAT_1_DIR}")
        sys.exit(1)
    if not beat_2_imgs:
        print(f"\n   ❌ ERROR: No hay imagenes en {BEAT_2_DIR}")
        sys.exit(1)
    if not beat_3_imgs:
        print(f"\n   ❌ ERROR: No hay imagenes en {BEAT_3_DIR}")
        sys.exit(1)

    font_path = find_font()
    print(f"   Font: {font_path or 'default'}")

    # Generar videos
    generated = []
    for i in range(1, num_videos + 1):
        try:
            path = generate_video(i, beat_1_imgs, beat_2_imgs, beat_3_imgs, font_path)
            generated.append(path)
        except Exception as e:
            print(f"\n   ❌ Error en video {i}: {e}")
            continue

    # Resumen
    print(f"\n\n{'='*60}")
    print(f"   RESUMEN")
    print(f"{'='*60}")
    print(f"   Generados: {len(generated)}/{num_videos}")
    print(f"   Output: {OUTPUT_DIR}")
    if generated:
        total_size = sum(p.stat().st_size for p in generated) / (1024 * 1024)
        print(f"   Tamaño total: {total_size:.1f} MB")
    print(f"{'='*60}\n")

    return generated


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - Generador bulk meme")
    parser.add_argument("--num", type=int, default=10, help="Numero de videos a generar (default: 10)")
    args = parser.parse_args()

    generate_bulk(num_videos=args.num)
