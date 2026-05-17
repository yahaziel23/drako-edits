#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador de Meme Reaction Videos

Formato: Imagen (meme) arriba + Video clip abajo
         Sin crop: ambos se muestran completos con fondo negro si sobra.
         El split se calcula dinamicamente segun el tamano real del meme y clip.
         El meme siempre ocupa mas espacio que el clip (min 55%, max 75%).
         Caption superpuesto en la frontera meme/video (opcional).

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

# Layout limits: el meme siempre ocupa mas que el clip
MEME_MIN_RATIO = 0.55  # Minimo 55% del alto para el meme
MEME_MAX_RATIO = 0.75  # Maximo 75% del alto para el meme

# Font config
STROKE_WIDTH = 4

# Caption font size options
CAPTION_SIZES = {
    "S": 45,
    "M": 65,
    "L": 85,
    "XL": 110,
}


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def get_images_from_dir(directory):
    """Obtiene todas las imagenes de un directorio."""
    extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    if not directory.exists():
        return []
    imgs = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    return sorted(imgs)


def get_videos_from_dir(directory):
    """Obtiene todos los videos de un directorio."""
    extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    if not directory.exists():
        return []
    vids = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    return sorted(vids)


def get_audio_files(directory):
    """Obtiene todos los audios de un directorio."""
    extensions = {'.mp3', '.wav', '.ogg', '.m4a', '.aac'}
    if not directory.exists():
        return []
    auds = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    return sorted(auds)


def load_clips_index():
    """Carga el indice de clips catalogados."""
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return []


def find_font():
    """Busca una fuente bold disponible en el sistema."""
    font_paths = [
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/IMPACT.TTF",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for p in font_paths:
        if Path(p).exists():
            return p
    return None


def fit_image_to_area(img, area_width, area_height):
    """
    Escala la imagen para que quepa COMPLETA dentro del area (sin crop).
    Retorna imagen con fondo negro del tamano exacto del area.
    """
    img_ratio = img.width / img.height
    area_ratio = area_width / area_height

    if img_ratio > area_ratio:
        # Imagen mas ancha que el area: limitar por ancho
        new_w = area_width
        new_h = int(area_width / img_ratio)
    else:
        # Imagen mas alta que el area: limitar por alto
        new_h = area_height
        new_w = int(area_height * img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Centrar sobre fondo negro
    canvas = Image.new("RGB", (area_width, area_height), (0, 0, 0))
    x = (area_width - new_w) // 2
    y = (area_height - new_h) // 2
    canvas.paste(img, (x, y))
    return canvas


def calculate_layout(meme_path, clip_size):
    """
    Calcula el split dinamico entre meme y clip basado en sus dimensiones reales.
    Ambos se muestran completos (fit, no crop).
    El meme siempre ocupa entre MEME_MIN_RATIO y MEME_MAX_RATIO del alto total.

    Args:
        meme_path: Path a la imagen del meme
        clip_size: tupla (width, height) del clip de video

    Returns:
        (meme_area_height, clip_area_height) en pixeles
    """
    # Calcular altura natural del meme si lo fiteamos al ancho completo
    meme_img = Image.open(meme_path)
    meme_ratio = meme_img.width / meme_img.height
    meme_natural_h = int(VIDEO_WIDTH / meme_ratio)

    # Calcular altura natural del clip si lo fiteamos al ancho completo
    clip_w, clip_h = clip_size
    clip_ratio = clip_w / clip_h
    clip_natural_h = int(VIDEO_WIDTH / clip_ratio)

    total_needed = meme_natural_h + clip_natural_h

    if total_needed <= VIDEO_HEIGHT:
        # Ambos caben, distribuir espacio sobrante
        meme_area_h = meme_natural_h + (VIDEO_HEIGHT - total_needed) // 2
        clip_area_h = VIDEO_HEIGHT - meme_area_h
    else:
        # No caben juntos: escalar proporcionalmente
        scale = VIDEO_HEIGHT / total_needed
        meme_area_h = int(meme_natural_h * scale)
        clip_area_h = VIDEO_HEIGHT - meme_area_h

    # Aplicar limites: meme siempre entre 55% y 75%
    min_meme_h = int(VIDEO_HEIGHT * MEME_MIN_RATIO)
    max_meme_h = int(VIDEO_HEIGHT * MEME_MAX_RATIO)

    if meme_area_h < min_meme_h:
        meme_area_h = min_meme_h
        clip_area_h = VIDEO_HEIGHT - meme_area_h
    elif meme_area_h > max_meme_h:
        meme_area_h = max_meme_h
        clip_area_h = VIDEO_HEIGHT - meme_area_h

    return meme_area_h, clip_area_h


def render_caption(text, font_path, font_size):
    """Renderiza caption con stroke negro. Retorna numpy array RGBA."""
    try:
        font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
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


# =============================================================================
# SELECCION INTERACTIVA
# =============================================================================

def select_meme():
    """Muestra memes disponibles y deja elegir."""
    memes = get_images_from_dir(MEMES_DIR)
    if not memes:
        print(f"\n   [X] No hay memes en {MEMES_DIR}")
        sys.exit(1)

    print("\n   Memes disponibles:")
    for i, m in enumerate(memes, 1):
        print(f"      {i}. {m.name}")

    while True:
        choice = input("\n   Meme (numero o nombre): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(memes):
                return memes[idx]
        else:
            for m in memes:
                if m.stem.lower() == choice.lower() or m.name.lower() == choice.lower():
                    return m
        print("   [!] No valido, intenta de nuevo.")


def select_clip():
    """Muestra clips disponibles (del indice o directorio) y deja elegir."""
    index = load_clips_index()

    if index:
        print("\n   Clips catalogados:")
        for i, entry in enumerate(index, 1):
            name = entry.get("name", entry.get("file", "???"))
            duration = entry.get("duration", "?")
            desc = entry.get("description", "")
            print(f"      {i}. {name} ({duration}s) {desc}")

        while True:
            choice = input("\n   Clip (numero): ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(index):
                    entry = index[idx]
                    clip_file = entry.get("file", entry.get("name", ""))
                    clip_path = CLIPS_DIR / clip_file
                    if clip_path.exists():
                        return clip_path
                    print(f"   [!] Archivo no encontrado: {clip_path}")
            print("   [!] No valido.")
    else:
        clips = get_videos_from_dir(CLIPS_DIR)
        if not clips:
            print(f"\n   [X] No hay clips en {CLIPS_DIR}")
            sys.exit(1)

        print("\n   Clips disponibles:")
        for i, c in enumerate(clips, 1):
            print(f"      {i}. {c.name}")

        while True:
            choice = input("\n   Clip (numero o nombre): ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(clips):
                    return clips[idx]
            else:
                for c in clips:
                    if c.stem.lower() == choice.lower() or c.name.lower() == choice.lower():
                        return c
            print("   [!] No valido.")


def select_music():
    """Muestra audios disponibles y deja elegir."""
    music_files = get_audio_files(MUSIC_DIR)

    if not music_files:
        print(f"\n   [!] No hay audios en {MUSIC_DIR}. Continuando sin musica.")
        return None

    print("\n   Musica disponible:")
    print(f"      0. (Sin musica - usar audio del clip)")
    for i, m in enumerate(music_files, 1):
        print(f"      {i}. {m.name}")

    while True:
        choice = input("\n   Musica (numero, 0=sin musica): ").strip()
        if choice == "0" or choice.lower() in ("sin", "none", "no"):
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(music_files):
                return music_files[idx]
        print("   [!] No valido.")


def select_caption():
    """Pregunta si quiere caption y su tamano."""
    caption_input = input("\n   Caption (texto, o Enter para sin caption): ").strip()

    if not caption_input:
        return None, None

    print("   Tamano: S / M / L / XL")
    size = input("   Tamano (default M): ").strip().upper()
    if size not in CAPTION_SIZES:
        size = "M"

    return caption_input, CAPTION_SIZES[size]


# =============================================================================
# GENERADOR
# =============================================================================

def generate_video(meme_path, clip_path, music_path, caption_text, caption_size, output_name=None):
    """Genera el video de meme reaction."""
    print(f"\n{'='*50}")
    print(f"   GENERANDO MEME REACTION")
    print(f"   Meme: {meme_path.name}")
    print(f"   Clip: {clip_path.name}")
    print(f"   Musica: {music_path.name if music_path else '(audio del clip)'}")
    print(f"   Caption: {caption_text or '(sin)'}")
    print(f"{'='*50}")

    # Cargar clip para obtener dimensiones
    print("\n   Cargando clip...")
    video_clip = VideoFileClip(str(clip_path))
    clip_size = video_clip.size  # (width, height)

    # Calcular layout dinamico
    meme_area_h, clip_area_h = calculate_layout(meme_path, clip_size)
    meme_pct = (meme_area_h / VIDEO_HEIGHT) * 100
    clip_pct = (clip_area_h / VIDEO_HEIGHT) * 100
    print(f"   Layout dinamico: meme={meme_area_h}px ({meme_pct:.0f}%) | clip={clip_area_h}px ({clip_pct:.0f}%)")

    # Preparar meme (fit completo, sin crop, fondo negro)
    print("   Procesando meme...")
    meme_img = Image.open(meme_path).convert("RGB")
    meme_fitted = fit_image_to_area(meme_img, VIDEO_WIDTH, meme_area_h)
    meme_array = np.array(meme_fitted)

    # Determinar duracion
    if music_path:
        audio_clip = AudioFileClip(str(music_path))
        duration = min(video_clip.duration, audio_clip.duration)
    else:
        audio_clip = None
        duration = video_clip.duration

    print(f"   Duracion del video: {duration:.2f}s")

    # Recortar clip a duracion
    video_clip = video_clip.subclipped(0, min(duration, video_clip.duration - 0.01))

    # Procesar frames del clip: fit completo dentro del area, fondo negro
    def process_frame(frame):
        img = Image.fromarray(frame)
        fitted = fit_image_to_area(img, VIDEO_WIDTH, clip_area_h)
        return np.array(fitted)

    print("   Procesando frames del clip...")
    processed_clip = video_clip.image_transform(process_frame)

    # Crear clip de meme (imagen estatica)
    meme_clip = ImageClip(meme_array).with_duration(duration)

    # Posicionar: meme arriba, clip abajo
    meme_clip = meme_clip.with_position((0, 0))
    processed_clip = processed_clip.with_position((0, meme_area_h))

    # Construir composicion
    layers = [meme_clip, processed_clip]

    # Caption (en la frontera meme/clip)
    if caption_text and caption_size:
        font_path = find_font()
        caption_img = render_caption(caption_text, font_path, caption_size)
        x_pos = max(0, (VIDEO_WIDTH - caption_img.shape[1]) // 2)
        y_pos = meme_area_h - caption_img.shape[0] // 2  # Centrado en la frontera
        cap_clip = (ImageClip(caption_img, transparent=True)
                    .with_position((x_pos, y_pos))
                    .with_duration(duration))
        layers.append(cap_clip)

    # Componer
    print("   Componiendo video...")
    final = CompositeVideoClip(layers, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(duration)

    # Audio
    if audio_clip:
        audio_clip = audio_clip.subclipped(0, min(duration, audio_clip.duration - 0.01))
        final = final.with_audio(audio_clip)
    else:
        if video_clip.audio:
            final = final.with_audio(video_clip.audio)

    # Export
    if output_name is None:
        output_name = f"meme_{meme_path.stem}_{clip_path.stem}"

    output_path = OUTPUT_DIR / f"{output_name}.mp4"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("   Renderizando...")
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
    if audio_clip:
        audio_clip.close()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\n   [OK] Listo: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 50)
    print("   DRAKO EDITS - Meme Reaction Generator")
    print("=" * 50)

    # Verificar carpetas
    if not MEMES_DIR.exists():
        print(f"\n   [X] No existe: {MEMES_DIR}")
        sys.exit(1)
    if not CLIPS_DIR.exists():
        print(f"\n   [X] No existe: {CLIPS_DIR}")
        sys.exit(1)

    # 1. Seleccionar meme
    meme_path = select_meme()
    print(f"   -> Meme: {meme_path.name}")

    # 2. Seleccionar clip
    clip_path = select_clip()
    print(f"   -> Clip: {clip_path.name}")

    # 3. Seleccionar musica
    music_path = select_music()
    print(f"   -> Musica: {music_path.name if music_path else '(audio del clip)'}")

    # 4. Caption
    caption_text, caption_size = select_caption()

    # 5. Nombre de salida
    output_name = input("\n   Nombre del video (sin .mp4, Enter=auto): ").strip()
    if not output_name:
        output_name = None

    # 6. Generar
    generate_video(meme_path, clip_path, music_path, caption_text, caption_size, output_name)

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
