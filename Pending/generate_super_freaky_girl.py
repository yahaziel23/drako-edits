#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador: "Super Freaky Girl"

Genera videos del trend de Nicki Minaj con imagenes rapidas + deletreo de nombre.
Soporta modos: letters, characters, mixed.

Uso:
    python generate_super_freaky_girl.py --name DANIELA
    python generate_super_freaky_girl.py --name SOFIA --caption "Yo cuando veo a"
    python generate_super_freaky_girl.py --name DANIELA --intro_theme roses
    python generate_super_freaky_girl.py --batch nombres.txt

Estructura requerida:
    assets/super_freaky_girl/
        audio/super_freaky_girl.mp3
        intro/roses/     (imagenes rapidas de rosas)
        intro/love/      (corazones, parejas)
        intro/shitpost/  (memes cursed)
        intro/custom/    (otros)
        letters/         (A.png, B.png, ... Z.png)
        sequences/       (carpetas para modo characters)
        output/          (videos generados)
"""

import os
import sys
import random
import argparse
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, CompositeVideoClip, concatenate_videoclips


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "super_freaky_girl"

AUDIO_PATH = ASSETS_DIR / "audio" / "super_freaky_girl.mp3"
INTRO_DIR = ASSETS_DIR / "intro"
LETTERS_DIR = ASSETS_DIR / "letters"
SEQUENCES_DIR = ASSETS_DIR / "sequences"
OUTPUT_DIR = ASSETS_DIR / "output"

# Timing del audio (en segundos)
AUDIO_FULL_DURATION = 11.540
SPELLING_START = 4.342

# Intro: 8 imagenes en los primeros 4.342 segundos
INTRO_IMAGE_COUNT = 8
INTRO_DURATION = SPELLING_START  # 4.342s
INTRO_TIME_PER_IMAGE = INTRO_DURATION / INTRO_IMAGE_COUNT  # ~0.543s

# Spelling: maximo disponible del 4.342 al 11.540
SPELLING_MAX_DURATION = AUDIO_FULL_DURATION - SPELLING_START  # 7.198s
MAX_TIME_PER_LETTER = 0.6  # maximo 0.6 segundos por letra/item

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Letter sizing: las letras se muestran mas chicas con fondo blanco
LETTER_SCALE = 0.55  # 55% del ancho del video

# Caption config
FONT_SIZE = 80
STROKE_WIDTH = 5
CAPTION_Y = int(VIDEO_HEIGHT * 0.45)  # Caption en la mitad superior


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


def resize_letter_on_white(img_path):
    """
    Coloca la imagen de la letra centrada sobre un fondo blanco 1080x1920.
    La letra se escala a LETTER_SCALE del ancho del video (mas chica).
    """
    img = Image.open(img_path).convert("RGBA")

    # Calcular nuevo tamano manteniendo proporcion
    target_w = int(VIDEO_WIDTH * LETTER_SCALE)
    ratio = target_w / img.width
    target_h = int(img.height * ratio)

    # Si la altura escalada es muy grande, limitar por altura
    max_h = int(VIDEO_HEIGHT * 0.5)
    if target_h > max_h:
        ratio = max_h / img.height
        target_w = int(img.width * ratio)
        target_h = max_h

    img = img.resize((target_w, target_h), Image.LANCZOS)

    # Crear fondo blanco y pegar centrado
    canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (255, 255, 255))
    x = (VIDEO_WIDTH - target_w) // 2
    y = (VIDEO_HEIGHT - target_h) // 2
    canvas.paste(img, (x, y), img if img.mode == "RGBA" else None)

    return canvas


def find_font():
    """Busca una fuente bold disponible en el sistema."""
    font_paths = [
        # Windows
        "C:/Windows/Fonts/impact.ttf",
        "C:/Windows/Fonts/IMPACT.TTF",
        "C:/Windows/Fonts/arialbd.ttf",
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


def find_letter_image(letter):
    """
    Busca una imagen para la letra dada en la carpeta letters/.
    Si hay variantes (A_1.png, A_2.png), elige una random.
    Retorna el path o None si no existe.
    """
    letter = letter.upper()
    candidates = []
    for img_path in get_images_from_dir(LETTERS_DIR):
        name = img_path.stem.upper()
        # Match exacto (A) o variante (A_1, A_2, A_bow)
        if name == letter or name.startswith(f"{letter}_"):
            candidates.append(img_path)
    
    if not candidates:
        print(f"   [!] No se encontro imagen para la letra '{letter}'")
        return None
    
    return random.choice(candidates)


def get_sequence_images(sequence_name):
    """Obtiene las imagenes de una secuencia (modo characters)."""
    seq_dir = SEQUENCES_DIR / sequence_name
    if not seq_dir.exists():
        print(f"   [!] Secuencia '{sequence_name}' no encontrada en {SEQUENCES_DIR}")
        return []
    return get_images_from_dir(seq_dir)


def render_caption(text, font_path):
    """
    Renderiza el caption fijo (ej. "Cuando se llama...") con stroke negro.
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


# =============================================================================
# CALCULO DE TIMING
# =============================================================================

def calculate_spelling_timing(name_length):
    """
    Calcula la duracion de cada letra y la duracion total del video.
    
    Reglas:
    - Total items = letras del nombre + 1 imagen de cierre
    - Cada item dura maximo MAX_TIME_PER_LETTER (0.6s)
    - Si el nombre es largo y no cabe en el audio, se distribuye parejo
    - El audio se CORTA despues del ultimo item (no se usa todo si sobra)
    
    Retorna: (time_per_letter, total_video_duration)
    """
    total_items = name_length + 1  # letras + imagen de cierre
    
    # Cuanto duraria si usamos el maximo por item
    spelling_needed = total_items * MAX_TIME_PER_LETTER
    
    if spelling_needed <= SPELLING_MAX_DURATION:
        # Cabe con 0.6s por item: usamos 0.6 y cortamos audio
        time_per_letter = MAX_TIME_PER_LETTER
        total_video_duration = SPELLING_START + spelling_needed
    else:
        # No cabe: distribuir parejo en todo el audio disponible
        time_per_letter = SPELLING_MAX_DURATION / total_items
        total_video_duration = AUDIO_FULL_DURATION
    
    return time_per_letter, total_video_duration


# =============================================================================
# GENERADOR PRINCIPAL
# =============================================================================

def generate_video(name, mode="letters", caption="Cuando se llama...",
                   intro_theme="roses", sequence_name=None, output_name=None):
    """
    Genera un video del formato Super Freaky Girl.
    
    Args:
        name: Nombre a deletrear (modo letters) o label (modo characters)
        mode: "letters", "characters", o "mixed"
        caption: Texto fijo del caption
        intro_theme: Tema de imagenes para la intro (roses, love, shitpost, custom)
        sequence_name: Nombre de la secuencia (solo para modo characters)
        output_name: Nombre del archivo de salida (sin extension)
    """
    print(f"\n{'='*50}")
    print(f"   SUPER FREAKY GIRL -- {name.upper()}")
    print(f"   Modo: {mode} | Intro: {intro_theme}")
    print(f"   Caption: \"{caption}\"")
    print(f"{'='*50}")

    # --- Validaciones ---
    if not AUDIO_PATH.exists():
        print(f"   [X] Audio no encontrado: {AUDIO_PATH}")
        return None

    intro_path = INTRO_DIR / intro_theme
    intro_images = get_images_from_dir(intro_path)
    if len(intro_images) < 1:
        print(f"   [X] No hay imagenes en intro/{intro_theme}/")
        return None

    # --- Preparar imagenes de spelling segun modo ---
    name_upper = name.upper()
    spelling_images = []

    if mode == "letters":
        for letter in name_upper:
            img_path = find_letter_image(letter)
            if img_path is None:
                print(f"   [X] Falta letra '{letter}'. Abortando.")
                return None
            spelling_images.append(img_path)

    elif mode == "characters":
        if not sequence_name:
            print(f"   [X] Modo 'characters' requiere --sequence")
            return None
        seq_imgs = get_sequence_images(sequence_name)
        if not seq_imgs:
            return None
        spelling_images = seq_imgs

    elif mode == "mixed":
        for letter in name_upper:
            img_path = find_letter_image(letter)
            if img_path is None:
                print(f"   [X] Falta letra '{letter}'. Abortando.")
                return None
            spelling_images.append(img_path)

    num_spelling = len(spelling_images)
    print(f"   Letras/items a mostrar: {num_spelling}")

    # --- Calcular timing ---
    time_per_letter, total_video_duration = calculate_spelling_timing(num_spelling)
    spelling_total = time_per_letter * (num_spelling + 1)
    print(f"   Tiempo por letra: {time_per_letter:.3f}s")
    print(f"   Spelling total (letras + cierre): {spelling_total:.3f}s")
    print(f"   Duracion total del video: {total_video_duration:.3f}s")
    print(f"   Intro: {INTRO_IMAGE_COUNT} imgs x {INTRO_TIME_PER_IMAGE:.3f}s = {INTRO_DURATION:.3f}s")

    # --- Seleccionar imagenes de intro ---
    if len(intro_images) >= INTRO_IMAGE_COUNT:
        selected_intro = random.sample(intro_images, INTRO_IMAGE_COUNT)
    else:
        selected_intro = random.choices(intro_images, k=INTRO_IMAGE_COUNT)

    # Imagen de cierre: una mas del intro (random)
    closing_image_path = random.choice(intro_images)

    # --- Cargar audio (cortado a la duracion calculada) ---
    audio_clip = AudioFileClip(str(AUDIO_PATH)).subclipped(0, total_video_duration)

    # --- Construir clips ---
    font_path = find_font()
    all_clips = []
    current_time = 0.0

    # FASE 1: Intro rapida (8 imagenes)
    print(f"\n   Construyendo intro...")
    for i, img_path in enumerate(selected_intro):
        img = resize_to_vertical(img_path)
        img_array = np.array(img)
        clip = ImageClip(img_array).with_start(current_time).with_duration(INTRO_TIME_PER_IMAGE)
        all_clips.append(clip)
        current_time += INTRO_TIME_PER_IMAGE

    # FASE 2: Spelling (letra por letra, con fondo blanco)
    print(f"   Construyendo spelling...")
    for i, img_path in enumerate(spelling_images):
        img = resize_letter_on_white(img_path)
        img_array = np.array(img)
        clip = ImageClip(img_array).with_start(current_time).with_duration(time_per_letter)
        all_clips.append(clip)
        current_time += time_per_letter

    # FASE 3: Imagen de cierre (se queda hasta el final del audio cortado)
    print(f"   Construyendo cierre...")
    closing_img = resize_to_vertical(closing_image_path)
    closing_array = np.array(closing_img)
    closing_clip = ImageClip(closing_array).with_start(current_time).with_duration(time_per_letter)
    all_clips.append(closing_clip)

    # --- Caption fijo (durante todo el video) ---
    caption_img = render_caption(caption, font_path)
    x_pos = max(0, (VIDEO_WIDTH - caption_img.shape[1]) // 2)
    caption_clip = (ImageClip(caption_img, transparent=True)
                    .with_position((x_pos, CAPTION_Y))
                    .with_start(0)
                    .with_duration(total_video_duration))
    all_clips.append(caption_clip)

    # --- Componer video final ---
    print(f"   Componiendo video...")
    final = CompositeVideoClip(all_clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(total_video_duration).with_audio(audio_clip)

    # --- Export ---
    if output_name is None:
        output_name = f"sfg_{name_upper}_{intro_theme}"
    
    output_path = OUTPUT_DIR / f"{output_name}.mp4"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
    print(f"\n   [OK] Listo: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# =============================================================================
# GENERACION POR LOTE (BATCH)
# =============================================================================

def generate_batch(file_path, mode="letters", caption="Cuando se llama...",
                   intro_theme="roses"):
    """
    Genera videos en lote desde un archivo de texto.
    Cada linea = un nombre.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        print(f"[X] Archivo de lote no encontrado: {file_path}")
        return

    names = [line.strip() for line in file_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"\n[BATCH] Generando {len(names)} videos en lote...")
    print(f"   Modo: {mode} | Tema: {intro_theme}")
    print(f"   Caption: \"{caption}\"")

    results = []
    for i, name in enumerate(names, 1):
        print(f"\n--- [{i}/{len(names)}] ---")
        result = generate_video(
            name=name,
            mode=mode,
            caption=caption,
            intro_theme=intro_theme
        )
        if result:
            results.append(result)

    print(f"\n{'='*50}")
    print(f"   LOTE COMPLETO: {len(results)}/{len(names)} videos generados")
    print(f"{'='*50}")


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Drako Edits - Generador Super Freaky Girl",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python generate_super_freaky_girl.py --name DANIELA
  python generate_super_freaky_girl.py --name SOFIA --caption "Yo cuando veo a"
  python generate_super_freaky_girl.py --name ANA --intro_theme love
  python generate_super_freaky_girl.py --batch nombres.txt
  python generate_super_freaky_girl.py --mode characters --sequence hello_kitty --name "Hello Kitty"
        """
    )

    parser.add_argument("--name", type=str, help="Nombre a deletrear (o label para characters)")
    parser.add_argument("--mode", type=str, default="letters",
                        choices=["letters", "characters", "mixed"],
                        help="Modo de generacion (default: letters)")
    parser.add_argument("--caption", type=str, default="Cuando se llama...",
                        help="Caption fijo del video (default: 'Cuando se llama...')")
    parser.add_argument("--intro_theme", type=str, default="roses",
                        choices=["roses", "love", "shitpost", "custom"],
                        help="Tema de imagenes para la intro (default: roses)")
    parser.add_argument("--sequence", type=str, default=None,
                        help="Nombre de la secuencia (solo para modo characters)")
    parser.add_argument("--output", type=str, default=None,
                        help="Nombre del archivo de salida (sin .mp4)")
    parser.add_argument("--batch", type=str, default=None,
                        help="Archivo .txt con un nombre por linea para generar en lote")

    args = parser.parse_args()

    # Validar que hay input
    if not args.name and not args.batch:
        parser.print_help()
        print("\n[X] Necesitas --name o --batch")
        sys.exit(1)

    # Header
    print("\n>>> Drako Edits -- Super Freaky Girl Generator")
    print(f"   Assets: {ASSETS_DIR}")
    print(f"   Output: {OUTPUT_DIR}")

    # Verificar assets basicos
    if not AUDIO_PATH.exists():
        print(f"\n[X] Audio no encontrado: {AUDIO_PATH}")
        print(f"   Pon el archivo 'super_freaky_girl.mp3' en assets/super_freaky_girl/audio/")
        sys.exit(1)

    # Generar
    if args.batch:
        generate_batch(
            file_path=args.batch,
            mode=args.mode,
            caption=args.caption,
            intro_theme=args.intro_theme
        )
    else:
        generate_video(
            name=args.name,
            mode=args.mode,
            caption=args.caption,
            intro_theme=args.intro_theme,
            sequence_name=args.sequence,
            output_name=args.output
        )

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
