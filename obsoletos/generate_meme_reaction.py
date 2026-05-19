#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador de Meme Reaction Videos

Formato: Imagen (meme) arriba + Video clip abajo
         Sin crop: ambos se muestran completos con fondo blanco si sobra.
         El split se calcula dinamicamente segun el tamano real del meme y clip.
         El meme siempre ocupa mas espacio que el clip (min 65%, max 75%).
         Caption superpuesto en la frontera meme/video (opcional).
         Usa | para salto de linea en el caption.
         Auto-detecta y remueve barras negras de los clips.

Fuentes de material:
    - Imagenes: tools_output/posts/ (descargadas de IG)
    - Videos:   tools_output/videos/ (descargados de YT)
    - Audios:   tools_output/audios/ (descargados de YT)

Configs (JSONs):
    - assets/meme_reaction/configs/ (cada JSON = una combinacion reutilizable)

Output:
    - output/meme_reaction/

Modos:
    1. Desde JSON config (elige un JSON existente y genera)
    2. Manual (elige imagen, clip, audio, caption interactivamente)
       -> Opcion de guardar la combinacion como JSON para reutilizar

Uso:
    python generate_meme_reaction.py
    python generate_meme_reaction.py --config "assets/meme_reaction/configs/meme01.json"
"""

import sys
import io
import json
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

SCRIPT_DIR = Path(__file__).parent  # raiz del proyecto

# Fuentes de material (tools_output)
IMAGES_DIR = SCRIPT_DIR / "tools_output" / "posts"
VIDEOS_DIR = SCRIPT_DIR / "tools_output" / "videos"
AUDIOS_DIR = SCRIPT_DIR / "tools_output" / "audios"

# Configs y output
CONFIGS_DIR = SCRIPT_DIR / "assets" / "meme_reaction" / "configs"
OUTPUT_DIR = SCRIPT_DIR / "output" / "meme_reaction"

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Layout limits: el meme siempre ocupa mas que el clip
MEME_MIN_RATIO = 0.65
MEME_MAX_RATIO = 0.75

# Background color
BG_COLOR = (255, 255, 255)

# Font config
STROKE_WIDTH = 4
CAPTION_SIZES = {
    "S": 45,
    "M": 65,
    "L": 85,
    "XL": 110,
}

# Auto-crop config
BLACK_BAR_THRESHOLD = 15
BLACK_BAR_MIN_ROWS = 5


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

def get_images_recursive(directory):
    """Obtiene todas las imagenes de un directorio (recursivo)."""
    extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    if not directory.exists():
        return []
    imgs = [f for f in directory.rglob("*") if f.suffix.lower() in extensions]
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


def get_configs():
    """Obtiene todos los JSON configs disponibles."""
    if not CONFIGS_DIR.exists():
        return []
    return sorted(CONFIGS_DIR.glob("*.json"))


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


def detect_black_bars(frame):
    """Detecta barras negras arriba y abajo de un frame."""
    if len(frame.shape) == 3:
        gray = np.mean(frame, axis=2)
    else:
        gray = frame

    height = gray.shape[0]

    top_crop = 0
    for row in range(height):
        if np.mean(gray[row]) < BLACK_BAR_THRESHOLD:
            top_crop = row + 1
        else:
            break

    bottom_crop = 0
    for row in range(height - 1, -1, -1):
        if np.mean(gray[row]) < BLACK_BAR_THRESHOLD:
            bottom_crop = height - row
        else:
            break

    if top_crop < BLACK_BAR_MIN_ROWS:
        top_crop = 0
    if bottom_crop < BLACK_BAR_MIN_ROWS:
        bottom_crop = 0

    return top_crop, bottom_crop


def fit_image_to_area(img, area_width, area_height):
    """Escala imagen para que quepa completa (fit, no crop). Fondo blanco."""
    img_ratio = img.width / img.height
    area_ratio = area_width / area_height

    if img_ratio > area_ratio:
        new_w = area_width
        new_h = int(area_width / img_ratio)
    else:
        new_h = area_height
        new_w = int(area_height * img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (area_width, area_height), BG_COLOR)
    x = (area_width - new_w) // 2
    y = (area_height - new_h) // 2
    canvas.paste(img, (x, y))
    return canvas


def calculate_layout(meme_path, clip_size):
    """Calcula split dinamico meme/clip."""
    meme_img = Image.open(meme_path)
    meme_ratio = meme_img.width / meme_img.height
    meme_natural_h = int(VIDEO_WIDTH / meme_ratio)

    clip_w, clip_h = clip_size
    clip_ratio = clip_w / clip_h
    clip_natural_h = int(VIDEO_WIDTH / clip_ratio)

    total_needed = meme_natural_h + clip_natural_h

    if total_needed <= VIDEO_HEIGHT:
        meme_area_h = meme_natural_h + (VIDEO_HEIGHT - total_needed) // 2
        clip_area_h = VIDEO_HEIGHT - meme_area_h
    else:
        scale = VIDEO_HEIGHT / total_needed
        meme_area_h = int(meme_natural_h * scale)
        clip_area_h = VIDEO_HEIGHT - meme_area_h

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
    """Renderiza caption con stroke. Usa | como salto de linea."""
    text = text.replace("|", "\n")

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
              stroke_width=STROKE_WIDTH, stroke_fill=(0, 0, 0, 255),
              align="center")

    return np.array(img)


# =============================================================================
# JSON CONFIG
# =============================================================================

def load_config(config_path):
    """Carga un JSON config y retorna dict con paths resueltos."""
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))

    # Resolver paths relativos a la raiz del proyecto
    resolved = {
        "name": config.get("name", Path(config_path).stem),
        "meme": SCRIPT_DIR / config["meme"],
        "clip": SCRIPT_DIR / config["clip"],
        "music": SCRIPT_DIR / config["music"] if config.get("music") else None,
        "caption": config.get("caption", None),
        "caption_size": config.get("caption_size", "M"),
    }

    return resolved


def save_config(name, meme_path, clip_path, music_path, caption_text, caption_size_key):
    """Guarda la combinacion actual como JSON config para reutilizar."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    # Guardar paths relativos a la raiz
    config = {
        "name": name,
        "meme": str(meme_path.relative_to(SCRIPT_DIR)),
        "clip": str(clip_path.relative_to(SCRIPT_DIR)),
        "music": str(music_path.relative_to(SCRIPT_DIR)) if music_path else None,
        "caption": caption_text,
        "caption_size": caption_size_key,
    }

    # Nombre del archivo JSON
    safe_name = name.replace(" ", "_").lower()
    config_file = CONFIGS_DIR / f"{safe_name}.json"

    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   [OK] Config guardado: {config_file.relative_to(SCRIPT_DIR)}")
    return config_file


# =============================================================================
# SELECCION INTERACTIVA
# =============================================================================

def select_image():
    """Muestra imagenes disponibles en tools_output/posts/ y deja elegir."""
    images = get_images_recursive(IMAGES_DIR)
    if not images:
        print(f"\n   [X] No hay imagenes en {IMAGES_DIR}")
        print(f"       Descarga posts con: python tools/instagram/posts_nologin.py")
        sys.exit(1)

    print(f"\n   Imagenes disponibles ({len(images)}):")
    for i, img in enumerate(images, 1):
        # Mostrar path relativo a posts/ para que se vea de que perfil es
        rel = img.relative_to(IMAGES_DIR)
        print(f"      {i}. {rel}")

    while True:
        choice = input("\n   Imagen (numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(images):
                return images[idx]
        print("   [!] No valido.")


def select_clip():
    """Muestra videos disponibles en tools_output/videos/ y deja elegir."""
    clips = get_videos_from_dir(VIDEOS_DIR)
    if not clips:
        print(f"\n   [X] No hay videos en {VIDEOS_DIR}")
        print(f"       Descarga clips con: python tools/youtube/download_video_yt.py")
        sys.exit(1)

    print(f"\n   Clips disponibles ({len(clips)}):")
    for i, c in enumerate(clips, 1):
        print(f"      {i}. {c.name}")

    while True:
        choice = input("\n   Clip (numero): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(clips):
                return clips[idx]
        print("   [!] No valido.")


def select_music():
    """Muestra audios disponibles en tools_output/audios/ y deja elegir."""
    music_files = get_audio_files(AUDIOS_DIR)

    if not music_files:
        print(f"\n   [!] No hay audios en {AUDIOS_DIR}. Usando audio del clip.")
        return None

    print(f"\n   Musica disponible ({len(music_files)}):")
    print(f"      0. (Sin musica - usar audio del clip)")
    for i, m in enumerate(music_files, 1):
        print(f"      {i}. {m.name}")

    while True:
        choice = input("\n   Musica (numero, 0=sin musica): ").strip()
        if choice == "0" or choice.lower() in ("sin", "none", "no", ""):
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(music_files):
                return music_files[idx]
        print("   [!] No valido.")


def select_caption():
    """Pregunta caption y tamano. Retorna (text, size_key)."""
    caption_input = input("\n   Caption (texto, | para salto de linea, Enter=sin): ").strip()

    if not caption_input:
        return None, None

    print("   Tamano: S / M / L / XL")
    size = input("   Tamano (default M): ").strip().upper()
    if size not in CAPTION_SIZES:
        size = "M"

    return caption_input, size


# =============================================================================
# GENERADOR
# =============================================================================

def generate_video(meme_path, clip_path, music_path, caption_text, caption_size_key, output_name=None):
    """Genera el video de meme reaction."""
    caption_size = CAPTION_SIZES.get(caption_size_key, CAPTION_SIZES["M"]) if caption_size_key else None

    print(f"\n{'='*50}")
    print(f"   GENERANDO MEME REACTION")
    print(f"   Meme:    {meme_path.name}")
    print(f"   Clip:    {clip_path.name}")
    print(f"   Musica:  {music_path.name if music_path else '(audio del clip)'}")
    print(f"   Caption: {caption_text or '(sin)'} [{caption_size_key or '-'}]")
    print(f"{'='*50}")

    # Cargar clip
    print("\n   Cargando clip...")
    video_clip = VideoFileClip(str(clip_path))

    # Auto-detectar barras negras
    first_frame = video_clip.get_frame(0.1)
    top_crop, bottom_crop = detect_black_bars(first_frame)

    if top_crop > 0 or bottom_crop > 0:
        orig_h = video_clip.size[1]
        print(f"   [auto-crop] Barras: top={top_crop}px, bottom={bottom_crop}px")
        video_clip = video_clip.cropped(
            x1=0, y1=top_crop,
            x2=video_clip.size[0], y2=video_clip.size[1] - bottom_crop
        )
        print(f"   [auto-crop] {orig_h}px -> {video_clip.size[1]}px")

    clip_size = video_clip.size

    # Layout dinamico
    meme_area_h, clip_area_h = calculate_layout(meme_path, clip_size)
    print(f"   Layout: meme={meme_area_h}px ({meme_area_h/VIDEO_HEIGHT*100:.0f}%) | clip={clip_area_h}px")

    # Preparar meme
    print("   Procesando meme...")
    meme_img = Image.open(meme_path).convert("RGB")
    meme_fitted = fit_image_to_area(meme_img, VIDEO_WIDTH, meme_area_h)
    meme_array = np.array(meme_fitted)

    # Duracion
    if music_path:
        audio_clip = AudioFileClip(str(music_path))
        duration = min(video_clip.duration, audio_clip.duration)
    else:
        audio_clip = None
        duration = video_clip.duration

    print(f"   Duracion: {duration:.2f}s")

    video_clip = video_clip.subclipped(0, min(duration, video_clip.duration - 0.01))

    # Procesar frames del clip
    def process_frame(frame):
        img = Image.fromarray(frame)
        fitted = fit_image_to_area(img, VIDEO_WIDTH, clip_area_h)
        return np.array(fitted)

    print("   Procesando frames...")
    processed_clip = video_clip.image_transform(process_frame)

    # Composicion
    meme_clip = ImageClip(meme_array).with_duration(duration)
    meme_clip = meme_clip.with_position((0, 0))
    processed_clip = processed_clip.with_position((0, meme_area_h))

    layers = [meme_clip, processed_clip]

    # Caption
    if caption_text and caption_size:
        font_path = find_font()
        caption_img = render_caption(caption_text, font_path, caption_size)
        x_pos = max(0, (VIDEO_WIDTH - caption_img.shape[1]) // 2)
        y_pos = meme_area_h - caption_img.shape[0] // 2
        cap_clip = (ImageClip(caption_img)
                    .with_position((x_pos, y_pos))
                    .with_duration(duration))
        layers.append(cap_clip)

    # Componer
    print("   Componiendo...")
    final = CompositeVideoClip(layers, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(duration)

    # Audio
    if audio_clip:
        audio_clip = audio_clip.subclipped(0, min(duration, audio_clip.duration - 0.01))
        final = final.with_audio(audio_clip)
    elif video_clip.audio:
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
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - Meme Reaction Generator")
    print("=" * 60)

    # Elegir modo
    configs = get_configs()

    print("\n   Modo:")
    print("      1. Manual (elegir imagen, clip, audio, caption)")
    if configs:
        print(f"      2. Desde config JSON ({len(configs)} disponibles)")

    mode = input("\n   Modo (1/2): ").strip()

    if mode == "2" and configs:
        # === MODO JSON ===
        print("\n   Configs disponibles:")
        for i, c in enumerate(configs, 1):
            cfg = json.loads(c.read_text(encoding="utf-8"))
            name = cfg.get("name", c.stem)
            caption = cfg.get("caption", "-")[:40]
            print(f"      {i}. {name} | caption: {caption}")

        while True:
            choice = input("\n   Config (numero): ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(configs):
                    break
            print("   [!] No valido.")

        config = load_config(configs[idx])

        # Validar que los archivos existan
        if not config["meme"].exists():
            print(f"   [X] Meme no encontrado: {config['meme']}")
            sys.exit(1)
        if not config["clip"].exists():
            print(f"   [X] Clip no encontrado: {config['clip']}")
            sys.exit(1)
        if config["music"] and not config["music"].exists():
            print(f"   [!] Musica no encontrada: {config['music']}. Continuando sin musica.")
            config["music"] = None

        generate_video(
            config["meme"], config["clip"], config["music"],
            config["caption"], config["caption_size"],
            config["name"]
        )

    else:
        # === MODO MANUAL ===
        # 1. Imagen
        meme_path = select_image()
        print(f"   -> Imagen: {meme_path.name}")

        # 2. Clip
        clip_path = select_clip()
        print(f"   -> Clip: {clip_path.name}")

        # 3. Musica
        music_path = select_music()
        print(f"   -> Musica: {music_path.name if music_path else '(audio del clip)'}")

        # 4. Caption
        caption_text, caption_size_key = select_caption()

        # 5. Nombre
        output_name = input("\n   Nombre del video (sin .mp4, Enter=auto): ").strip()
        if not output_name:
            output_name = None

        # 6. Generar
        generate_video(meme_path, clip_path, music_path, caption_text, caption_size_key, output_name)

        # 7. Guardar como config?
        save_choice = input("\n   Guardar esta combinacion como JSON config? (s/n): ").strip().lower()
        if save_choice == "s":
            config_name = input("   Nombre del config: ").strip()
            if not config_name:
                config_name = output_name or f"meme_{meme_path.stem}_{clip_path.stem}"
            save_config(config_name, meme_path, clip_path, music_path,
                        caption_text, caption_size_key)

    print("\n>>> Done!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Drako Edits - Meme Reaction Generator")
    parser.add_argument("--config", type=str, default=None,
                        help="Path a un JSON config para generar directamente")
    args = parser.parse_args()

    if args.config:
        config = load_config(args.config)
        if not config["meme"].exists():
            print(f"[X] Meme no encontrado: {config['meme']}")
            sys.exit(1)
        if not config["clip"].exists():
            print(f"[X] Clip no encontrado: {config['clip']}")
            sys.exit(1)
        generate_video(
            config["meme"], config["clip"], config["music"],
            config["caption"], config["caption_size"],
            config["name"]
        )
    else:
        main()
