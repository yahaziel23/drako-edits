#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador Generico (Interactivo + JSON rapido)

Genera videos simples: audio + imagenes por tramo + subtitulos.
Soporta configuracion paso a paso O carga rapida desde JSON.

Uso:
    python generate_generic.py              # Interactivo (paso a paso)
    python generate_generic.py --json config.json   # Config rapida desde archivo

Estructura requerida:
    assets/generic/
        audio/          <- audios disponibles
        images/
            foto1.png   <- imagen especifica (la pides por nombre)
            roses/      <- carpeta tematica (pides el nombre, elige random)
        output/         <- videos generados
        configs/        <- JSONs guardados para reusar

Formato del JSON:
    {
        "audio": "tikitiki.mp3",
        "output_name": "tikitiki",
        "background": "blur",
        "fill_mode": "cover",
        "segments": [
            {"end": 0.866, "image": "tiki1", "subtitle": "Tikki..."},
            {"end": 1.783, "image": "same", "subtitle": "same"},
            {"end": "ultimo", "image": "tiki2", "subtitle": null}
        ]
    }

    Reglas del JSON:
    - "background": "white", "black", o "blur" (imagen de fondo con transparencia)
    - "fill_mode": "cover" (cubre todo, puede cortar) o "fit" (completa, con fondo)
    - "image": nombre de archivo, nombre de carpeta, o "same" (misma que anterior)
    - "subtitle": texto, "same" (mismo que anterior), o null (sin subtitulo)
    - "end": numero (timestamp) o "ultimo" (hasta el final del audio)
"""

import os
import sys
import json
import random
import argparse
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
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
CONFIGS_DIR = ASSETS_DIR / "configs"

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Subtitle config
FONT_SIZE = 75
STROKE_WIDTH = 5
SUBTITLE_Y = int(VIDEO_HEIGHT * 0.50)

# Blur background config
BLUR_RADIUS = 30
BLUR_OPACITY = 0.4  # 0=invisible, 1=fully visible (lower = more transparent/dark)


# =============================================================================
# TRACKING DE IMAGENES USADAS (no repetir)
# =============================================================================

class ImagePool:
    """Trackea imagenes usadas por carpeta para no repetir."""

    def __init__(self):
        self.used = {}

    def get_random(self, folder_path):
        folder_name = folder_path.name
        all_imgs = get_images_from_dir(folder_path)

        if not all_imgs:
            return None

        if folder_name not in self.used:
            self.used[folder_name] = set()

        available = [img for img in all_imgs if img.name not in self.used[folder_name]]

        if not available:
            print(f"   [info] Pool agotado para '{folder_name}', reseteando...")
            self.used[folder_name] = set()
            available = all_imgs

        chosen = random.choice(available)
        self.used[folder_name].add(chosen.name)
        return chosen


# Pool global
image_pool = ImagePool()


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


def resize_cover(img_path):
    """Redimensiona para CUBRIR todo 1080x1920 (puede cortar bordes)."""
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


def resize_fit(img_path, background="black"):
    """
    Redimensiona para mostrar COMPLETA la imagen (sin cortar).
    El espacio sobrante se llena segun background:
    - "white": fondo blanco
    - "black": fondo negro
    - "blur": la misma imagen escalada a cover + blur + oscurecida
    """
    img = Image.open(img_path).convert("RGB")
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    img_ratio = img.width / img.height

    # Calcular tamano para fit (sin cortar)
    if img_ratio > target_ratio:
        # Imagen mas ancha: limitar por ancho
        new_w = VIDEO_WIDTH
        new_h = int(VIDEO_WIDTH / img_ratio)
    else:
        # Imagen mas alta: limitar por alto
        new_h = VIDEO_HEIGHT
        new_w = int(VIDEO_HEIGHT * img_ratio)

    img_fitted = img.resize((new_w, new_h), Image.LANCZOS)

    # Crear fondo segun tipo
    if background == "blur":
        # Fondo = misma imagen escalada a cover + blur + oscurecida
        if img_ratio > target_ratio:
            bg_h = VIDEO_HEIGHT
            bg_w = int(bg_h * img_ratio)
        else:
            bg_w = VIDEO_WIDTH
            bg_h = int(bg_w / img_ratio)

        bg = img.resize((bg_w, bg_h), Image.LANCZOS)
        left = (bg_w - VIDEO_WIDTH) // 2
        top = (bg_h - VIDEO_HEIGHT) // 2
        bg = bg.crop((left, top, left + VIDEO_WIDTH, top + VIDEO_HEIGHT))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=BLUR_RADIUS))

        # Oscurecer el fondo (mezclar con negro)
        dark = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
        canvas = Image.blend(dark, bg, BLUR_OPACITY)
    elif background == "white":
        canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (255, 255, 255))
    else:  # black
        canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))

    # Centrar imagen sobre el fondo
    x = (VIDEO_WIDTH - new_w) // 2
    y = (VIDEO_HEIGHT - new_h) // 2
    canvas.paste(img_fitted, (x, y))
    return canvas


def process_image(img_path, fill_mode, background):
    """Procesa una imagen segun el modo elegido."""
    if fill_mode == "cover":
        return resize_cover(img_path)
    else:  # fit
        return resize_fit(img_path, background)


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
    """Renderiza subtitulo centrado con stroke negro."""
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
    """Resuelve el input del usuario a un path de imagen."""
    direct_matches = []
    for img in get_images_from_dir(IMAGES_DIR):
        if img.stem.lower() == image_input.lower() or img.name.lower() == image_input.lower():
            direct_matches.append(img)

    if direct_matches:
        return random.choice(direct_matches)

    subfolder = IMAGES_DIR / image_input
    if subfolder.exists() and subfolder.is_dir():
        result = image_pool.get_random(subfolder)
        if result:
            return result
        else:
            print(f"   [!] La carpeta '{image_input}' esta vacia.")
            return None

    print(f"   [!] No se encontro '{image_input}' como imagen ni carpeta en images/")
    return None


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def show_available_images():
    """Muestra las imagenes y carpetas disponibles."""
    print("\n   Imagenes disponibles en assets/generic/images/:")

    direct_imgs = get_images_from_dir(IMAGES_DIR)
    if direct_imgs:
        print("   [Archivos directos (especificos)]:")
        for img in direct_imgs:
            print(f"      - {img.name}")

    subfolders = get_subfolders(IMAGES_DIR)
    if subfolders:
        print("   [Carpetas (random de ahi)]:")
        for folder in subfolders:
            total = len(get_images_from_dir(folder))
            used = len(image_pool.used.get(folder.name, set()))
            print(f"      - {folder.name}/ ({total} imgs, {total - used} disponibles)")

    if not direct_imgs and not subfolders:
        print("   [!] No hay imagenes ni carpetas aun.")


def ask_visual_settings():
    """Pregunta las opciones visuales al inicio: fill mode y background."""
    print("\n   --- Opciones visuales ---")

    # Fill mode
    print("\n   Como mostrar las imagenes?")
    print("      1. cover  - Cubren todo (puede cortar bordes)")
    print("      2. fit    - Se ven completas (con fondo donde sobre)")
    fill_choice = input("   Modo [1=cover / 2=fit]: ").strip()
    if fill_choice == "2" or fill_choice.lower() == "fit":
        fill_mode = "fit"
    else:
        fill_mode = "cover"

    # Background (solo relevante si es fit)
    background = "black"
    if fill_mode == "fit":
        print("\n   Que fondo usar donde sobre espacio?")
        print("      1. black  - Negro")
        print("      2. white  - Blanco")
        print("      3. blur   - Misma imagen borrosa de fondo")
        bg_choice = input("   Fondo [1=black / 2=white / 3=blur]: ").strip()
        if bg_choice == "2" or bg_choice.lower() == "white":
            background = "white"
        elif bg_choice == "3" or bg_choice.lower() == "blur":
            background = "blur"
        else:
            background = "black"

    print(f"\n   [OK] Modo: {fill_mode} | Fondo: {background}")
    return fill_mode, background


def ask_audio():
    """Pregunta por el audio a usar."""
    print("\n" + "=" * 50)
    print("   GENERADOR GENERICO - Drako Edits")
    print("=" * 50)

    audio_files = sorted(AUDIO_DIR.glob("*"))
    audio_files = [f for f in audio_files if f.suffix.lower() in {'.mp3', '.wav', '.ogg', '.m4a', '.aac'}]

    if not audio_files:
        print(f"\n   [X] No hay audios en {AUDIO_DIR}")
        sys.exit(1)

    print("\n   Audios disponibles:")
    for i, af in enumerate(audio_files, 1):
        print(f"      {i}. {af.name}")

    while True:
        choice = input("\n   Audio (nombre o numero): ").strip()

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(audio_files):
                return audio_files[idx]
            print("   [!] Numero fuera de rango.")
            continue

        for af in audio_files:
            if af.name.lower() == choice.lower() or af.stem.lower() == choice.lower():
                return af

        print(f"   [!] No se encontro '{choice}'.")


def ask_cuts(audio_duration):
    """Pregunta los cortes interactivamente."""
    segments = []
    previous_image = None
    previous_subtitle = None
    last_cut = 0.0
    json_segments = []

    print(f"\n   Duracion del audio: {audio_duration:.3f}s")
    print(f"   Define los cortes. En cada uno indicaras imagen y subtitulo.")
    print(f"   Opciones al pedir corte:")
    print(f"      - Un numero (ej. 4.59) = timestamp del corte")
    print(f"      - 'ultimo' = tramo final hasta el fin del audio")
    print(f"      - 'final' = cortar audio en el ultimo corte dado")
    print(f"   Para imagen/subtitulo: 'misma'/'mismo' repite el anterior.")
    print(f"   Las imagenes de carpeta NO se repiten hasta agotar el pool.")

    cut_num = 1
    while True:
        print(f"\n   --- Corte {cut_num} ---")
        print(f"   (Tramo actual empieza en {last_cut:.3f}s)")

        cut_input = input("   Corte (timestamp / ultimo / final): ").strip().lower()

        if cut_input == "final":
            if not segments:
                print("   [!] No hay cortes previos. Da al menos un corte primero.")
                continue
            print(f"   [OK] Video terminara en {last_cut:.3f}s (audio cortado ahi).")
            return segments, last_cut, json_segments

        if cut_input == "ultimo":
            end_time = audio_duration
            print(f"   Tramo: {last_cut:.3f}s -> {end_time:.3f}s (hasta el final)")

            img_path, img_input_raw = ask_image(previous_image)
            if img_path is None:
                continue

            subtitle, sub_input_raw = ask_subtitle(previous_subtitle)

            segments.append({
                "start": last_cut,
                "end": end_time,
                "image_path": img_path,
                "subtitle": subtitle
            })
            json_segments.append({
                "end": "ultimo",
                "image": img_input_raw,
                "subtitle": sub_input_raw
            })
            print(f"   [OK] Tramo final guardado.")
            return segments, audio_duration, json_segments

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

        img_path, img_input_raw = ask_image(previous_image)
        if img_path is None:
            continue

        subtitle, sub_input_raw = ask_subtitle(previous_subtitle)

        segments.append({
            "start": last_cut,
            "end": cut_time,
            "image_path": img_path,
            "subtitle": subtitle
        })
        json_segments.append({
            "end": cut_time,
            "image": img_input_raw,
            "subtitle": sub_input_raw
        })

        previous_image = img_path
        previous_subtitle = subtitle
        last_cut = cut_time
        cut_num += 1

        print(f"   [OK] Tramo guardado. Siguiente...")


def ask_image(previous_image):
    """Pregunta la imagen. Retorna (Path, raw_input_string)."""
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
            return previous_image, "same"

        resolved = resolve_image(img_input)
        if resolved:
            print(f"   -> Imagen: {resolved.name}")
            return resolved, img_input

        print("   [!] Intenta de nuevo.")


def ask_subtitle(previous_subtitle):
    """Pregunta el subtitulo. Retorna (text_or_None, raw_input_string)."""
    prompt = "   Subtitulo"
    if previous_subtitle:
        prompt += " ('mismo' para repetir)"
    prompt += ": "

    sub_input = input(prompt).strip()

    if sub_input.lower() in ("mismo", "misma", "same") and previous_subtitle:
        print(f"   -> Usando mismo: \"{previous_subtitle}\"")
        return previous_subtitle, "same"

    if not sub_input or sub_input.lower() in ("nada", "none", "sin"):
        return None, None

    return sub_input, sub_input


def ask_output_name():
    """Pregunta el nombre del archivo de salida."""
    name = input("\n   Nombre del video (sin .mp4): ").strip()
    if not name:
        name = "generic_video"
    return name


# =============================================================================
# CONFIGURACION RAPIDA (JSON)
# =============================================================================

def load_from_json(json_path):
    """Carga configuracion desde un archivo JSON."""
    json_path = Path(json_path)
    if not json_path.exists():
        alt_path = CONFIGS_DIR / json_path.name
        if alt_path.exists():
            json_path = alt_path
        else:
            print(f"   [X] JSON no encontrado: {json_path}")
            sys.exit(1)

    config = json.loads(json_path.read_text(encoding="utf-8"))

    audio_name = config["audio"]
    audio_path = AUDIO_DIR / audio_name
    if not audio_path.exists():
        print(f"   [X] Audio no encontrado: {audio_path}")
        sys.exit(1)

    audio_duration = get_audio_duration(audio_path)
    output_name = config.get("output_name", "generic_video")
    fill_mode = config.get("fill_mode", "cover")
    background = config.get("background", "black")

    segments = []
    last_cut = 0.0
    previous_image = None
    previous_subtitle = None

    for i, seg_config in enumerate(config["segments"]):
        end_raw = seg_config["end"]
        if end_raw == "ultimo":
            end_time = audio_duration
        else:
            end_time = float(end_raw)

        img_raw = seg_config["image"]
        if img_raw and img_raw.lower() == "same":
            if previous_image is None:
                print(f"   [X] Segmento {i+1}: 'same' pero no hay imagen anterior.")
                sys.exit(1)
            img_path = previous_image
        else:
            img_path = resolve_image(img_raw)
            if img_path is None:
                print(f"   [X] Segmento {i+1}: no se pudo resolver imagen '{img_raw}'.")
                sys.exit(1)

        sub_raw = seg_config.get("subtitle")
        if sub_raw and str(sub_raw).lower() == "same":
            subtitle = previous_subtitle
        elif sub_raw is None or str(sub_raw).lower() in ("null", "none", "nada", "sin", ""):
            subtitle = None
        else:
            subtitle = str(sub_raw)

        segments.append({
            "start": last_cut,
            "end": end_time,
            "image_path": img_path,
            "subtitle": subtitle
        })

        previous_image = img_path
        previous_subtitle = subtitle
        last_cut = end_time

    total_duration = last_cut
    return audio_path, segments, total_duration, output_name, fill_mode, background


def save_config_json(audio_name, json_segments, output_name, fill_mode, background):
    """Guarda la configuracion como JSON para reusar."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "audio": audio_name,
        "output_name": output_name,
        "fill_mode": fill_mode,
        "background": background,
        "segments": json_segments
    }

    config_path = CONFIGS_DIR / f"{output_name}.json"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"   [OK] Config guardada: {config_path}")
    print(f"   Reusar con: python generate_generic.py --json {config_path.name}")


# =============================================================================
# GENERADOR
# =============================================================================

def generate_video(audio_path, segments, total_duration, output_name, fill_mode="cover", background="black"):
    """Genera el video con los segmentos definidos."""
    print(f"\n{'='*50}")
    print(f"   GENERANDO VIDEO")
    print(f"   Audio: {audio_path.name}")
    print(f"   Segmentos: {len(segments)}")
    print(f"   Duracion: {total_duration:.3f}s")
    print(f"   Modo: {fill_mode} | Fondo: {background}")
    print(f"{'='*50}")

    font_path = find_font()

    # Cargar audio con ajuste de precision
    audio_clip = AudioFileClip(str(audio_path))
    safe_duration = min(total_duration, audio_clip.duration - 0.01)
    if safe_duration < total_duration:
        print(f"   [info] Ajustando duracion: {total_duration:.3f}s -> {safe_duration:.3f}s (precision de audio)")
        total_duration = safe_duration
    audio_clip = audio_clip.subclipped(0, total_duration)

    all_clips = []

    for i, seg in enumerate(segments):
        start = seg["start"]
        end = min(seg["end"], total_duration)
        duration = end - start
        if duration <= 0:
            continue
        img_path = seg["image_path"]
        subtitle = seg["subtitle"]

        print(f"   Segmento {i+1}: {start:.3f}s -> {end:.3f}s | img: {img_path.name} | sub: {subtitle or '(sin)'}")

        # Procesar imagen segun modo
        img = process_image(img_path, fill_mode, background)
        img_array = np.array(img)
        clip = ImageClip(img_array).with_start(start).with_duration(duration)
        all_clips.append(clip)

        if subtitle:
            sub_img = render_subtitle(subtitle, font_path)
            x_pos = max(0, (VIDEO_WIDTH - sub_img.shape[1]) // 2)
            sub_clip = (ImageClip(sub_img, transparent=True)
                        .with_position((x_pos, SUBTITLE_Y))
                        .with_start(start)
                        .with_duration(duration))
            all_clips.append(sub_clip)

    print(f"\n   Componiendo video...")
    final = CompositeVideoClip(all_clips, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(total_duration).with_audio(audio_clip)

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
    parser = argparse.ArgumentParser(
        description="Drako Edits - Generador Generico",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python generate_generic.py                     # Interactivo
  python generate_generic.py --json tikitiki.json # Config rapida
        """
    )
    parser.add_argument("--json", type=str, default=None,
                        help="Archivo JSON con la configuracion (rapido)")
    args = parser.parse_args()

    # Verificar carpetas
    if not AUDIO_DIR.exists():
        print(f"[X] No existe: {AUDIO_DIR}")
        sys.exit(1)
    if not IMAGES_DIR.exists():
        print(f"[X] No existe: {IMAGES_DIR}")
        sys.exit(1)

    # --- MODO JSON (rapido) ---
    if args.json:
        print("\n>>> Drako Edits -- Generador Generico (Config Rapida)")
        audio_path, segments, total_duration, output_name, fill_mode, background = load_from_json(args.json)

        print(f"\n   Audio: {audio_path.name}")
        print(f"   Segmentos: {len(segments)}")
        print(f"   Duracion: {total_duration:.3f}s")
        print(f"   Modo: {fill_mode} | Fondo: {background}")
        print(f"   Output: {output_name}.mp4")

        generate_video(audio_path, segments, total_duration, output_name, fill_mode, background)
        print("\n>>> Done!")
        return

    # --- MODO INTERACTIVO (paso a paso) ---
    audio_path = ask_audio()
    audio_duration = get_audio_duration(audio_path)
    print(f"\n   Audio seleccionado: {audio_path.name}")
    print(f"   Duracion: {audio_duration:.3f}s")

    # Preguntar opciones visuales
    fill_mode, background = ask_visual_settings()

    # Cortes
    segments, total_duration, json_segments = ask_cuts(audio_duration)

    if not segments:
        print("\n   [X] No se definieron segmentos. Saliendo.")
        sys.exit(1)

    # Resumen
    print(f"\n{'='*50}")
    print(f"   RESUMEN")
    print(f"{'='*50}")
    print(f"   Modo: {fill_mode} | Fondo: {background}")
    for i, seg in enumerate(segments, 1):
        print(f"   {i}. [{seg['start']:.3f}s - {seg['end']:.3f}s] img: {seg['image_path'].name} | sub: {seg['subtitle'] or '(sin)'}")
    print(f"   Duracion total: {total_duration:.3f}s")

    # Confirmar
    confirm = input("\n   Generar? (s/n): ").strip().lower()
    if confirm not in ("s", "si", "y", "yes", ""):
        print("   Cancelado.")
        sys.exit(0)

    # Nombre
    output_name = ask_output_name()

    # Generar
    generate_video(audio_path, segments, total_duration, output_name, fill_mode, background)

    # Ofrecer guardar JSON
    save = input("\n   Guardar config como JSON para reusar? (s/n): ").strip().lower()
    if save in ("s", "si", "y", "yes", ""):
        save_config_json(audio_path.name, json_segments, output_name, fill_mode, background)

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
