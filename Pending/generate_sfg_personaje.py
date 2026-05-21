#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Super Freaky Girl: Personaje (V2)

Genera videos del formato SFG pero para personajes/artistas en vez de nombres.
Primera parte: imagenes rapidas de un tema (atrevimiento, gusto, etc.)
Segunda parte: imagenes del personaje/artista (Milo J, Bad Bunny, etc.)

Usa el mismo audio y timing que generate_super_freaky_girl.py

Uso:
    python generate_sfg_personaje.py
    python generate_sfg_personaje.py --json config.json

Estructura requerida:
    assets/sfg_personaje/
        audio/super_freaky_girl.mp3
        intro/
            atrevimiento/   <- imagenes de intro (rapidas, tema "pecado")
            gusto/          <- otro tema de intro
            locura/         <- otro tema
        personajes/
            miloj/          <- imagenes del artista
            badbunny/       <- otro artista
        output/             <- videos generados
        configs/            <- JSONs guardados

Formato del JSON:
    {
        "intro_theme": "atrevimiento",
        "personaje": "miloj",
        "caption": "Cuando escuchas:",
        "output_name": "sfg_miloj",
        "num_personaje_imgs": 8
    }

    Reglas del JSON:
    - "intro_theme": nombre de carpeta en intro/
    - "personaje": nombre de carpeta en personajes/
    - "caption": texto que aparece durante TODO el video (| para salto de linea)
    - "output_name": nombre del mp4 sin extension
    - "num_personaje_imgs": cuantas imagenes mostrar en la segunda parte (default: 8)
"""

import os
import sys
import io
import json
import random
import argparse
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import ImageClip, AudioFileClip, CompositeVideoClip

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "sfg_personaje"

AUDIO_PATH = ASSETS_DIR / "audio" / "super_freaky_girl.mp3"
INTRO_DIR = ASSETS_DIR / "intro"
PERSONAJES_DIR = ASSETS_DIR / "personajes"
OUTPUT_DIR = ASSETS_DIR / "output"
CONFIGS_DIR = ASSETS_DIR / "configs"

# Timing del audio (en segundos) - mismo que SFG original
AUDIO_FULL_DURATION = 11.540
SPELLING_START = 4.342  # Aqui empieza la segunda parte

# Intro: 8 imagenes rapidas en los primeros 4.342 segundos
INTRO_IMAGE_COUNT = 8
INTRO_DURATION = SPELLING_START  # 4.342s
INTRO_TIME_PER_IMAGE = INTRO_DURATION / INTRO_IMAGE_COUNT  # ~0.543s

# Segunda parte: del 4.342 al 11.540
PART2_DURATION = AUDIO_FULL_DURATION - SPELLING_START  # 7.198s
DEFAULT_PERSONAJE_IMGS = 8  # Cuantas imagenes del personaje mostrar

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Caption config
FONT_SIZE = 80
STROKE_WIDTH = 5
CAPTION_Y = int(VIDEO_HEIGHT * 0.45)


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


def get_subfolders(directory):
    """Obtiene subcarpetas de un directorio."""
    if not directory.exists():
        return []
    return sorted([f for f in directory.iterdir() if f.is_dir()])


def resize_to_vertical(img_path):
    """Redimensiona y cropea cualquier imagen a 1080x1920 (cover)."""
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


def render_caption(text, font_path):
    """Renderiza caption con stroke negro. Usa | para salto de linea."""
    text = text.replace("|", "\n")

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
              stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255),
              align="center")

    return np.array(img)


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def ask_intro_theme():
    """Pregunta el tema de intro."""
    folders = get_subfolders(INTRO_DIR)
    if not folders:
        print(f"\n   [X] No hay carpetas en {INTRO_DIR}")
        print(f"       Crea carpetas con imagenes (ej: intro/atrevimiento/)")
        sys.exit(1)

    print("\n   Temas de intro disponibles:")
    for i, f in enumerate(folders, 1):
        count = len(get_images_from_dir(f))
        print(f"      {i}. {f.name}/ ({count} imgs)")

    while True:
        choice = input("\n   Tema de intro (nombre o numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(folders):
                return folders[idx].name
        else:
            for f in folders:
                if f.name.lower() == choice.lower():
                    return f.name
        print("   [!] No valido.")


def ask_personaje():
    """Pregunta el personaje."""
    folders = get_subfolders(PERSONAJES_DIR)
    if not folders:
        print(f"\n   [X] No hay carpetas en {PERSONAJES_DIR}")
        print(f"       Crea carpetas con imagenes (ej: personajes/miloj/)")
        sys.exit(1)

    print("\n   Personajes disponibles:")
    for i, f in enumerate(folders, 1):
        count = len(get_images_from_dir(f))
        print(f"      {i}. {f.name}/ ({count} imgs)")

    while True:
        choice = input("\n   Personaje (nombre o numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(folders):
                return folders[idx].name
        else:
            for f in folders:
                if f.name.lower() == choice.lower():
                    return f.name
        print("   [!] No valido.")


def ask_caption():
    """Pregunta el caption."""
    caption = input("\n   Caption (texto fijo, | = enter) [default: 'Cuando escuchas:']: ").strip()
    if not caption:
        caption = "Cuando escuchas:"
    return caption


def ask_num_personaje_imgs():
    """Pregunta cuantas imagenes del personaje mostrar."""
    print(f"\n   Cuantas imagenes del personaje en la 2da parte?")
    print(f"   (Duracion disponible: {PART2_DURATION:.3f}s)")
    print(f"   Mas imagenes = mas rapido cada una.")
    choice = input(f"   Cantidad [default: {DEFAULT_PERSONAJE_IMGS}]: ").strip()
    if choice.isdigit() and int(choice) > 0:
        return int(choice)
    return DEFAULT_PERSONAJE_IMGS


# =============================================================================
# GENERADOR
# =============================================================================

def generate_video(intro_theme, personaje, caption, output_name, num_personaje_imgs=DEFAULT_PERSONAJE_IMGS):
    """Genera el video SFG para personaje."""
    print(f"\n{'='*50}")
    print(f"   SFG PERSONAJE")
    print(f"   Intro: {intro_theme}")
    print(f"   Personaje: {personaje}")
    print(f"   Caption: \"{caption}\"")
    print(f"   Imgs personaje: {num_personaje_imgs}")
    print(f"{'='*50}")

    # --- Validaciones ---
    if not AUDIO_PATH.exists():
        print(f"   [X] Audio no encontrado: {AUDIO_PATH}")
        return None

    intro_path = INTRO_DIR / intro_theme
    intro_images = get_images_from_dir(intro_path)
    if not intro_images:
        print(f"   [X] No hay imagenes en intro/{intro_theme}/")
        return None

    personaje_path = PERSONAJES_DIR / personaje
    personaje_images = get_images_from_dir(personaje_path)
    if not personaje_images:
        print(f"   [X] No hay imagenes en personajes/{personaje}/")
        return None

    # --- Calcular timing de la segunda parte ---
    time_per_personaje = PART2_DURATION / num_personaje_imgs
    print(f"   Tiempo por img personaje: {time_per_personaje:.3f}s")
    print(f"   Intro: {INTRO_IMAGE_COUNT} imgs x {INTRO_TIME_PER_IMAGE:.3f}s")
    print(f"   Parte 2: {num_personaje_imgs} imgs x {time_per_personaje:.3f}s")

    # --- Seleccionar imagenes ---
    # Intro: 8 imagenes random (sin repetir si hay suficientes)
    if len(intro_images) >= INTRO_IMAGE_COUNT:
        selected_intro = random.sample(intro_images, INTRO_IMAGE_COUNT)
    else:
        selected_intro = random.choices(intro_images, k=INTRO_IMAGE_COUNT)

    # Personaje: N imagenes random
    if len(personaje_images) >= num_personaje_imgs:
        selected_personaje = random.sample(personaje_images, num_personaje_imgs)
    else:
        selected_personaje = random.choices(personaje_images, k=num_personaje_imgs)

    # --- Cargar audio ---
    audio_clip = AudioFileClip(str(AUDIO_PATH)).subclipped(0, AUDIO_FULL_DURATION)

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

    # FASE 2: Imagenes del personaje (full screen, cover)
    print(f"   Construyendo personaje...")
    for i, img_path in enumerate(selected_personaje):
        img = resize_to_vertical(img_path)
        img_array = np.array(img)
        clip = ImageClip(img_array).with_start(current_time).with_duration(time_per_personaje)
        all_clips.append(clip)
        current_time += time_per_personaje

    # --- Caption fijo (durante todo el video) ---
    if caption:
        caption_img = render_caption(caption, font_path)
        x_pos = max(0, (VIDEO_WIDTH - caption_img.shape[1]) // 2)
        caption_clip = (ImageClip(caption_img, transparent=True)
                        .with_position((x_pos, CAPTION_Y))
                        .with_start(0)
                        .with_duration(AUDIO_FULL_DURATION))
        all_clips.append(caption_clip)

    # --- Componer video final ---
    print(f"   Componiendo video...")
    final = CompositeVideoClip(all_clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(AUDIO_FULL_DURATION).with_audio(audio_clip)

    # --- Export ---
    if output_name is None:
        output_name = f"sfg_{personaje}"

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
# JSON
# =============================================================================

def load_from_json(json_path):
    """Carga configuracion desde JSON."""
    json_path = Path(json_path)
    if not json_path.exists():
        alt_path = CONFIGS_DIR / json_path.name
        if alt_path.exists():
            json_path = alt_path
        else:
            print(f"   [X] JSON no encontrado: {json_path}")
            sys.exit(1)

    config = json.loads(json_path.read_text(encoding="utf-8"))
    return config


def save_config_json(intro_theme, personaje, caption, output_name, num_personaje_imgs):
    """Guarda config como JSON."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "intro_theme": intro_theme,
        "personaje": personaje,
        "caption": caption,
        "output_name": output_name,
        "num_personaje_imgs": num_personaje_imgs
    }

    config_path = CONFIGS_DIR / f"{output_name}.json"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"   [OK] Config guardada: {config_path}")
    print(f"   Reusar con: python generate_sfg_personaje.py --json {config_path.name}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Drako Edits - SFG Personaje (V2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python generate_sfg_personaje.py                          # Interactivo
  python generate_sfg_personaje.py --json sfg_miloj.json    # Config rapida
        """
    )
    parser.add_argument("--json", type=str, default=None,
                        help="Archivo JSON con la configuracion")
    args = parser.parse_args()

    # Verificar carpetas base
    for d in [INTRO_DIR, PERSONAJES_DIR]:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            print(f"   [!] Se creo: {d}")

    # --- MODO JSON ---
    if args.json:
        print("\n>>> Drako Edits -- SFG Personaje (Config Rapida)")
        config = load_from_json(args.json)

        intro_theme = config["intro_theme"]
        personaje = config["personaje"]
        caption = config.get("caption", "Cuando escuchas:")
        output_name = config.get("output_name", f"sfg_{personaje}")
        num_personaje_imgs = config.get("num_personaje_imgs", DEFAULT_PERSONAJE_IMGS)

        print(f"   Intro: {intro_theme}")
        print(f"   Personaje: {personaje}")
        print(f"   Caption: \"{caption}\"")
        print(f"   Output: {output_name}.mp4")

        generate_video(intro_theme, personaje, caption, output_name, num_personaje_imgs)
        print("\n>>> Done!")
        return

    # --- MODO INTERACTIVO ---
    print("\n" + "=" * 50)
    print("   SFG PERSONAJE - Drako Edits")
    print("=" * 50)

    if not AUDIO_PATH.exists():
        print(f"\n   [X] Audio no encontrado: {AUDIO_PATH}")
        print(f"       Pon 'super_freaky_girl.mp3' en assets/sfg_personaje/audio/")
        sys.exit(1)

    # 1. Tema de intro
    intro_theme = ask_intro_theme()
    print(f"   -> Intro: {intro_theme}")

    # 2. Personaje
    personaje = ask_personaje()
    print(f"   -> Personaje: {personaje}")

    # 3. Caption
    caption = ask_caption()
    print(f"   -> Caption: \"{caption}\"")

    # 4. Cantidad de imagenes personaje
    num_personaje_imgs = ask_num_personaje_imgs()
    print(f"   -> Imgs personaje: {num_personaje_imgs}")

    # 5. Nombre
    output_name = input(f"\n   Nombre del video (sin .mp4) [default: sfg_{personaje}]: ").strip()
    if not output_name:
        output_name = f"sfg_{personaje}"

    # 6. Confirmar
    print(f"\n   Resumen: intro={intro_theme}, personaje={personaje}, caption=\"{caption}\", imgs={num_personaje_imgs}")
    confirm = input("   Generar? (s/n): ").strip().lower()
    if confirm not in ("s", "si", "y", "yes", ""):
        print("   Cancelado.")
        sys.exit(0)

    # 7. Generar
    generate_video(intro_theme, personaje, caption, output_name, num_personaje_imgs)

    # 8. Guardar JSON
    save = input("\n   Guardar config como JSON? (s/n): ").strip().lower()
    if save in ("s", "si", "y", "yes", ""):
        save_config_json(intro_theme, personaje, caption, output_name, num_personaje_imgs)

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
