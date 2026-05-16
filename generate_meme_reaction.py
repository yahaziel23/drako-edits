#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador de Meme Reaction Videos

Formato: Imagen (meme) arriba + Caption (texto medio) + Video clip abajo + Audio
Duracion: min(video, audio) o custom.

Uso:
    python generate_meme_reaction.py

Preparar antes:
    - Imagenes en assets/meme_reaction/memes/
    - Clips catalogados en assets/meme_reaction/clips/
    - Audios en assets/meme_reaction/music/
"""

import sys
import io
import os
import json
import random
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "meme_reaction"
CLIPS_DIR = ASSETS_DIR / "clips"
MEMES_DIR = ASSETS_DIR / "memes"
MUSIC_DIR = ASSETS_DIR / "music"
OUTPUT_DIR = SCRIPT_DIR / "output" / "meme_reaction"
INDEX_FILE = ASSETS_DIR / "clips_index.json"

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Font config
FONT_SIZE_CAPTION = 70
STROKE_WIDTH = 4


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def find_font():
    """Busca una fuente bold."""
    font_paths = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/IMPACT.TTF",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for p in font_paths:
        if Path(p).exists():
            return p
    return None


def get_video_duration(video_path):
    """Obtiene la duracion de un video en segundos."""
    clip = VideoFileClip(str(video_path))
    duration = clip.duration
    clip.close()
    return duration


def get_audio_duration(audio_path):
    """Obtiene la duracion de un audio en segundos."""
    clip = AudioFileClip(str(audio_path))
    duration = clip.duration
    clip.close()
    return duration


def resize_image_to_section(img_path, width, height):
    """Redimensiona imagen para que quepa en la seccion superior."""
    img = Image.open(img_path).convert("RGB")
    target_ratio = width / height
    img_ratio = img.width / img.height

    if img_ratio > target_ratio:
        new_h = height
        new_w = int(new_h * img_ratio)
    else:
        new_w = width
        new_h = int(new_w / img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return img.crop((left, top, left + width, top + height))


def render_caption(text, font_path, max_width=None):
    """Renderiza el caption con word wrap."""
    if max_width is None:
        max_width = VIDEO_WIDTH - 40

    try:
        font = ImageFont.truetype(font_path, FONT_SIZE_CAPTION) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    # Word wrap
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)

    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip()
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)

    # Renderizar
    line_height = FONT_SIZE_CAPTION + 10
    total_height = line_height * len(lines) + 20
    img = Image.new("RGBA", (VIDEO_WIDTH, total_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y = 10
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (VIDEO_WIDTH - tw) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255),
                  stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255))
        y += line_height

    return np.array(img)


def list_files(directory, extensions):
    """Lista archivos de un directorio con extensiones dadas."""
    if not directory.exists():
        return []
    return sorted([f for f in directory.iterdir() if f.suffix.lower() in extensions])


# =============================================================================
# GENERADOR DE VIDEO
# =============================================================================

def generate_video(meme_path, caption_text, clip_path, audio_path, duration, output_name):
    """Genera el video final con el formato meme reaction."""
    print(f"\n   Generando video...")

    font_path = find_font()

    # Calcular dimensiones de cada seccion
    caption_img = render_caption(caption_text, font_path)
    caption_h = caption_img.shape[0]

    top_h = int((VIDEO_HEIGHT - caption_h) * 0.50)  # Mitad superior para meme
    bottom_h = VIDEO_HEIGHT - top_h - caption_h      # Resto para video clip

    # 1. Imagen meme (arriba)
    meme_img = resize_image_to_section(meme_path, VIDEO_WIDTH, top_h)
    meme_array = np.array(meme_img)

    # 2. Video clip (abajo)
    video_clip = VideoFileClip(str(clip_path)).resized((VIDEO_WIDTH, bottom_h))
    if video_clip.duration > duration:
        video_clip = video_clip.subclipped(0, duration)

    # 3. Audio
    audio_clip = AudioFileClip(str(audio_path))
    if audio_clip.duration > duration:
        audio_clip = audio_clip.subclipped(0, duration)

    # 4. Componer video
    # Fondo negro
    bg = ImageClip(np.zeros((VIDEO_HEIGHT, VIDEO_WIDTH, 3), dtype=np.uint8)).with_duration(duration)

    # Meme arriba
    meme_clip = ImageClip(meme_array).with_duration(duration).with_position((0, 0))

    # Caption en el medio
    caption_clip = ImageClip(caption_img, transparent=True).with_duration(duration)
    caption_y = top_h
    caption_clip = caption_clip.with_position((0, caption_y))

    # Video clip abajo
    video_clip = video_clip.with_position((0, top_h + caption_h))

    # Composicion final
    final = CompositeVideoClip(
        [bg, meme_clip, caption_clip, video_clip],
        size=(VIDEO_WIDTH, VIDEO_HEIGHT)
    )
    final = final.with_duration(duration).with_audio(audio_clip)

    # Export
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / output_name

    print(f"   Renderizando {duration:.1f}s ...")
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
    video_clip.close()
    audio_clip.close()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"   [OK] Video generado: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def interactive_generate():
    """Flujo interactivo para generar un meme reaction video."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - MEME REACTION GENERATOR")
    print("=" * 60)

    # --- PASO 1: Imagen del meme ---
    print("\n--- PASO 1: Imagen del meme (arriba) ---")

    img_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    available_memes = list_files(MEMES_DIR, img_extensions)

    if not available_memes:
        print(f"   [X] No hay imagenes en {MEMES_DIR}")
        print(f"   Agrega imagenes a la carpeta memes/ y vuelve a correr.")
        return

    print(f"\n   Imagenes disponibles ({len(available_memes)}):")
    for i, img in enumerate(available_memes, 1):
        size_kb = img.stat().st_size / 1024
        print(f"     {i}. {img.name} ({size_kb:.0f} KB)")

    img_input = input("\n   Numero de imagen: ").strip()
    if not img_input.isdigit():
        print("   [X] Seleccion invalida. Saliendo.")
        return
    img_idx = int(img_input) - 1
    if img_idx < 0 or img_idx >= len(available_memes):
        print("   [X] Numero fuera de rango. Saliendo.")
        return
    meme_path = available_memes[img_idx]
    print(f"   Seleccionado: {meme_path.name}")

    # --- PASO 2: Caption ---
    print("\n--- PASO 2: Caption (texto del medio) ---")
    print("   Ejemplo: 'El men que escribio el post:'")
    caption = input("   Caption: ").strip()
    if not caption:
        print("   [X] Sin caption. Saliendo.")
        return

    # --- PASO 3: Video clip ---
    print("\n--- PASO 3: Video clip (parte de abajo) ---")

    available_clips = list_files(CLIPS_DIR, {'.mp4', '.webm', '.mov'})

    if not available_clips:
        print(f"   [X] No hay clips en {CLIPS_DIR}")
        print(f"   Usa catalog_clip.py para agregar clips.")
        return

    # Info del index si existe
    index = []
    if INDEX_FILE.exists():
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    index_map = {entry["file"]: entry for entry in index}

    print(f"\n   Clips disponibles ({len(available_clips)}):")
    for i, clip in enumerate(available_clips, 1):
        info = index_map.get(clip.name, {})
        tags = ", ".join(info.get("tags", [])) if info else ""
        desc = info.get("description", "")[:35]
        dur = get_video_duration(clip)
        label = f"{clip.name} ({dur:.1f}s)"
        if tags:
            label += f" [{tags}]"
        if desc:
            label += f" - {desc}"
        print(f"     {i}. {label}")

    clip_input = input("\n   Numero de clip: ").strip()
    if not clip_input.isdigit():
        print("   [X] Seleccion invalida. Saliendo.")
        return
    clip_idx = int(clip_input) - 1
    if clip_idx < 0 or clip_idx >= len(available_clips):
        print("   [X] Numero fuera de rango. Saliendo.")
        return
    clip_path = available_clips[clip_idx]
    clip_duration = get_video_duration(clip_path)
    print(f"   Seleccionado: {clip_path.name} ({clip_duration:.1f}s)")

    # --- PASO 4: Audio ---
    print("\n--- PASO 4: Audio (musica de fondo) ---")

    available_music = list_files(MUSIC_DIR, {'.mp3', '.wav', '.m4a', '.ogg'})

    if not available_music:
        print(f"   [X] No hay audios en {MUSIC_DIR}")
        print(f"   Usa download_audio.py para agregar musica.")
        return

    print(f"\n   Audios disponibles ({len(available_music)}):")
    for i, audio in enumerate(available_music, 1):
        dur = get_audio_duration(audio)
        print(f"     {i}. {audio.name} ({dur:.1f}s)")

    audio_input = input("\n   Numero de audio: ").strip()
    if not audio_input.isdigit():
        print("   [X] Seleccion invalida. Saliendo.")
        return
    audio_idx = int(audio_input) - 1
    if audio_idx < 0 or audio_idx >= len(available_music):
        print("   [X] Numero fuera de rango. Saliendo.")
        return
    audio_path = available_music[audio_idx]
    audio_duration = get_audio_duration(audio_path)
    print(f"   Seleccionado: {audio_path.name} ({audio_duration:.1f}s)")

    # --- PASO 5: Duracion ---
    print("\n--- PASO 5: Duracion ---")
    default_duration = min(clip_duration, audio_duration)
    print(f"   Video clip:  {clip_duration:.1f}s")
    print(f"   Audio:       {audio_duration:.1f}s")
    print(f"   Default:     {default_duration:.1f}s (el mas corto)")
    dur_input = input(f"\n   Duracion en segundos (ENTER para {default_duration:.1f}s): ").strip()

    if dur_input:
        try:
            duration = float(dur_input)
        except ValueError:
            print(f"   [!] No valido, usando default: {default_duration:.1f}s")
            duration = default_duration
    else:
        duration = default_duration

    print(f"   Duracion final: {duration:.1f}s")

    # --- PASO 6: Nombre del output ---
    print("\n--- PASO 6: Nombre del video ---")
    existing_output = list(OUTPUT_DIR.glob("*.mp4")) if OUTPUT_DIR.exists() else []
    next_num = len(existing_output) + 1
    default_name = f"meme_reaction_{next_num:03d}.mp4"

    name_input = input(f"   Nombre (ENTER para '{default_name}'): ").strip()
    output_name = name_input if name_input else default_name
    if not output_name.endswith(".mp4"):
        output_name += ".mp4"

    # --- GENERAR ---
    print("\n" + "=" * 60)
    print("   GENERANDO VIDEO")
    print("=" * 60)
    print(f"   Meme:     {meme_path.name}")
    print(f"   Caption:  {caption}")
    print(f"   Clip:     {clip_path.name}")
    print(f"   Audio:    {audio_path.name}")
    print(f"   Duracion: {duration:.1f}s")
    print(f"   Output:   {output_name}")

    result = generate_video(meme_path, caption, clip_path, audio_path, duration, output_name)

    if result:
        print(f"\n   [OK] Video listo: {result}")

    # Otro?
    otro = input("\n   Generar otro video? (s/n): ").strip().lower()
    if otro == 's':
        interactive_generate()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    interactive_generate()
