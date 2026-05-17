#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador Generico (Interactivo)

Genera videos simples: audio + imagenes por tramo + subtitulos.
El usuario define cortes (timestamps) y asigna imagen + subtitulo a cada tramo.

Uso:
    python generate_generic.py

Estructura requerida:
    assets/generic/
        audio/          <- audios disponibles
        images/
            foto1.png   <- imagen especifica (la pides por nombre)
            roses/      <- carpeta tematica (pides el nombre, elige random)
            memes/
        output/         <- videos generados

Flujo interactivo:
    1. Elige audio
    2. Se muestra duracion
    3. Define cortes (timestamps) con imagen + subtitulo para cada tramo
    4. Para terminar: "ultimo" (ultimo tramo hasta fin del audio) o "final" (corta ahi)
"""

import os
import sys
import random
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, CompositeVideoClip
from mutagen.mp3 import MP3
from mutagen import File as MutagenFile


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "generic"

AUDIO_DIR = ASSETS_DIR / "audio"
IMAGES_DIR = ASSETS_DIR / "images"
OUTPUT_DIR = ASSETS_DIR / "output"

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Subtitle config
FONT_SIZE = 75
STROKE_WIDTH = 5
SUBTITLE_Y = int(VIDEO_HEIGHT * 0.50)


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def get_audio_duration(audio_path):
    """Obtiene la duracion de un archivo de audio en segundos."""
    try:
        audio = MutagenFile(audio_path)
        if audio and audio.info:
            return audio.info.length
    except Exception:
        pass
    # Fallback con moviepy
    clip = AudioFileClip(str(audio_path))
    duration = clip.duration
    clip.close()
    return duration


def get_images_from_dir(directory):
    """Obtiene todas las imagenes de un directorio."""
    extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    if not directory.exists():
        return []
    imgs = [f for f in directory.iterdir() if f.suffix.lower() in extensions]
    return sorted(imgs)


def get_subfolders(directory):
    """Obtiene todas las subcarpetas de un directorio."""
    if not directory.exists():
        return []
    return sorted([f for f in directory.iterdir() if f.is_dir()])


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


def render_subtitle(text, font_path):
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


def resolve_image(image_input):
    """
    Resuelve el input del usuario a un path de imagen.
    - Si es un archivo directo en images/ -> usa ese
    - Si es el nombre de una subcarpeta -> elige random de ahi
    Retorna: Path o None
    """
    # Checar si es un archivo directo (con o sin extension)
    direct_matches = []
    for img in get_images_from_dir(IMAGES_DIR):
        if img.stem.lower() == image_input.lower() or img.name.lower() == image_input.lower():
            direct_matches.append(img)

    if direct_matches:
        return random.choice(direct_matches)

    # Checar si es una subcarpeta
    subfolder = IMAGES_DIR / image_input
    if subfolder.exists() and subfolder.is_dir():
        folder_imgs = get_images_from_dir(subfolder)
        if folder_imgs:
            return random.choice(folder_imgs)
        else:
            print(f"   [!] La carpeta '{image_input}' esta vacia.")
            return None

    # No encontrado
    print(f"   [!] No se encontro '{image_input}' como imagen ni carpeta en images/")
    return None


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def show_available_images():
    """Muestra las imagenes y carpetas disponibles."""
    print("\n   Imagenes disponibles en assets/generic/images/:")

    # Archivos directos
    direct_imgs = get_images_from_dir(IMAGES_DIR)
    if direct_imgs:
        print("   [Archivos directos (especificos)]:")
        for img in direct_imgs:
            print(f"      - {img.name}")

    # Subcarpetas
    subfolders = get_subfolders(IMAGES_DIR)
    if subfolders:
        print("   [Carpetas (random de ahi)]:")
        for folder in subfolders:
            count = len(get_images_from_dir(folder))
            print(f"      - {folder.name}/ ({count} imgs)")

    if not direct_imgs and not subfolders:
        print("   [!] No hay imagenes ni carpetas aun.")


def ask_audio():
    """Pregunta por el audio a usar."""
    print("\n" + "=" * 50)
    print("   GENERADOR GENERICO - Drako Edits")
    print("=" * 50)

    # Mostrar audios disponibles
    audio_files = sorted(AUDIO_DIR.glob("*"))
    audio_files = [f for f in audio_files if f.suffix.lower() in {'.mp3', '.wav', '.ogg', '.m4a', '.aac'}]

    if not audio_files:
        print(f"\n   [X] No hay audios en {AUDIO_DIR}")
        print(f"   Pon un audio ahi y vuelve a correr.")
        sys.exit(1)

    print("\n   Audios disponibles:")
    for i, af in enumerate(audio_files, 1):
        print(f"      {i}. {af.name}")

    while True:
        choice = input("\n   Audio (nombre o numero): ").strip()

        # Por numero
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(audio_files):
                return audio_files[idx]
            print("   [!] Numero fuera de rango.")
            continue

        # Por nombre
        for af in audio_files:
            if af.name.lower() == choice.lower() or af.stem.lower() == choice.lower():
                return af

        print(f"   [!] No se encontro '{choice}'.")


def ask_cuts(audio_duration):
    """
    Pregunta los cortes al usuario.
    Retorna lista de segmentos: [{start, end, image_path, subtitle}]
    """
    segments = []
    previous_image = None
    previous_subtitle = None
    last_cut = 0.0

    print(f"\n   Duracion del audio: {audio_duration:.3f}s")
    print(f"   Define los cortes. En cada uno indicaras imagen y subtitulo.")
    print(f"   Opciones al pedir corte:")
    print(f"      - Un numero (ej. 4.59) = timestamp del corte")
    print(f"      - 'ultimo' = tramo final hasta el fin del audio")
    print(f"      - 'final' = cortar audio en el ultimo corte dado")
    print(f"   Para imagen/subtitulo: 'misma'/'mismo' repite el anterior.")

    cut_num = 1
    while True:
        print(f"\n   --- Corte {cut_num} ---")
        print(f"   (Tramo actual empieza en {last_cut:.3f}s)")

        # Pedir corte
        cut_input = input("   Corte (timestamp / ultimo / final): ").strip().lower()

        # --- FINAL: cortar audio en el ultimo corte ---
        if cut_input == "final":
            if not segments:
                print("   [!] No hay cortes previos. Da al menos un corte primero.")
                continue
            print(f"   [OK] Video terminara en {last_cut:.3f}s (audio cortado ahi).")
            return segments, last_cut

        # --- ULTIMO: tramo hasta el final del audio ---
        if cut_input == "ultimo":
            end_time = audio_duration
            print(f"   Tramo: {last_cut:.3f}s -> {end_time:.3f}s (hasta el final)")

            # Pedir imagen
            img_path = ask_image(previous_image)
            if img_path is None:
                continue

            # Pedir subtitulo
            subtitle = ask_subtitle(previous_subtitle)

            segments.append({
                "start": last_cut,
                "end": end_time,
                "image_path": img_path,
                "subtitle": subtitle
            })
            print(f"   [OK] Tramo final guardado.")
            return segments, audio_duration

        # --- TIMESTAMP NUMERICO ---
        try:
            cut_time = float(cut_input)
        except ValueError:
            print("   [!] Entrada no valida. Usa un numero, 'ultimo', o 'final'.")
            continue

        if cut_time <= last_cut:
            print(f"   [!] El corte debe ser mayor a {last_cut:.3f}s.")
            continue

        if cut_time > audio_duration:
            print(f"   [!] El corte no puede ser mayor a la duracion ({audio_duration:.3f}s).")
            continue

        print(f"   Tramo: {last_cut:.3f}s -> {cut_time:.3f}s")

        # Pedir imagen
        img_path = ask_image(previous_image)
        if img_path is None:
            continue

        # Pedir subtitulo
        subtitle = ask_subtitle(previous_subtitle)

        segments.append({
            "start": last_cut,
            "end": cut_time,
            "image_path": img_path,
            "subtitle": subtitle
        })

        previous_image = img_path
        previous_subtitle = subtitle
        last_cut = cut_time
        cut_num += 1

        print(f"   [OK] Tramo guardado. Siguiente...")


def ask_image(previous_image):
    """Pregunta la imagen para un tramo. Retorna Path o None."""
    show_available_images()

    prompt = "   Imagen"
    if previous_image:
        prompt += " ('misma' para repetir)"
    prompt += ": "

    while True:
        img_input = input(prompt).strip()

        if not img_input:
            print("   [!] Escribe algo.")
            continue

        if img_input.lower() in ("misma", "mismo", "same") and previous_image:
            print(f"   -> Usando misma: {previous_image.name}")
            return previous_image

        resolved = resolve_image(img_input)
        if resolved:
            print(f"   -> Imagen: {resolved.name}")
            return resolved

        print("   [!] Intenta de nuevo.")


def ask_subtitle(previous_subtitle):
    """Pregunta el subtitulo para un tramo."""
    prompt = "   Subtitulo"
    if previous_subtitle:
        prompt += " ('mismo' para repetir)"
    prompt += ": "

    sub_input = input(prompt).strip()

    if sub_input.lower() in ("mismo", "misma", "same") and previous_subtitle:
        print(f"   -> Usando mismo: \"{previous_subtitle}\"")
        return previous_subtitle

    if not sub_input or sub_input.lower() in ("nada", "none", "sin", ""):
        return None

    return sub_input


def ask_output_name():
    """Pregunta el nombre del archivo de salida."""
    name = input("\n   Nombre del video (sin .mp4): ").strip()
    if not name:
        name = "generic_video"
    return name


# =============================================================================
# GENERADOR
# =============================================================================

def generate_video(audio_path, segments, total_duration, output_name):
    """Genera el video con los segmentos definidos."""
    print(f"\n{'='*50}")
    print(f"   GENERANDO VIDEO")
    print(f"   Audio: {audio_path.name}")
    print(f"   Segmentos: {len(segments)}")
    print(f"   Duracion: {total_duration:.3f}s")
    print(f"{'='*50}")

    font_path = find_font()
    audio_clip = AudioFileClip(str(audio_path)).subclipped(0, total_duration)

    all_clips = []

    # Construir clips por segmento
    for i, seg in enumerate(segments):
        start = seg["start"]
        end = seg["end"]
        duration = end - start
        img_path = seg["image_path"]
        subtitle = seg["subtitle"]

        print(f"   Segmento {i+1}: {start:.3f}s -> {end:.3f}s | img: {img_path.name} | sub: {subtitle or '(sin)'}")

        # Imagen de fondo
        img = resize_to_vertical(img_path)
        img_array = np.array(img)
        clip = ImageClip(img_array).with_start(start).with_duration(duration)
        all_clips.append(clip)

        # Subtitulo (si hay)
        if subtitle:
            sub_img = render_subtitle(subtitle, font_path)
            x_pos = max(0, (VIDEO_WIDTH - sub_img.shape[1]) // 2)
            sub_clip = (ImageClip(sub_img, transparent=True)
                        .with_position((x_pos, SUBTITLE_Y))
                        .with_start(start)
                        .with_duration(duration))
            all_clips.append(sub_clip)

    # Componer
    print(f"\n   Componiendo video...")
    final = CompositeVideoClip(all_clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(total_duration).with_audio(audio_clip)

    # Export
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
# MAIN
# =============================================================================

def main():
    # Verificar carpetas
    if not AUDIO_DIR.exists():
        print(f"[X] No existe: {AUDIO_DIR}")
        sys.exit(1)
    if not IMAGES_DIR.exists():
        print(f"[X] No existe: {IMAGES_DIR}")
        sys.exit(1)

    # 1. Pedir audio
    audio_path = ask_audio()
    audio_duration = get_audio_duration(audio_path)
    print(f"\n   Audio seleccionado: {audio_path.name}")
    print(f"   Duracion: {audio_duration:.3f}s")

    # 2. Pedir cortes
    segments, total_duration = ask_cuts(audio_duration)

    if not segments:
        print("\n   [X] No se definieron segmentos. Saliendo.")
        sys.exit(1)

    # 3. Resumen
    print(f"\n{'='*50}")
    print(f"   RESUMEN")
    print(f"{'='*50}")
    for i, seg in enumerate(segments, 1):
        print(f"   {i}. [{seg['start']:.3f}s - {seg['end']:.3f}s] img: {seg['image_path'].name} | sub: {seg['subtitle'] or '(sin)'}")
    print(f"   Duracion total: {total_duration:.3f}s")

    # 4. Confirmar
    confirm = input("\n   Generar? (s/n): ").strip().lower()
    if confirm not in ("s", "si", "y", "yes", ""):
        print("   Cancelado.")
        sys.exit(0)

    # 5. Nombre de salida
    output_name = ask_output_name()

    # 6. Generar
    generate_video(audio_path, segments, total_duration, output_name)

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
