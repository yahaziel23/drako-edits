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
         Auto-detecta y remueve barras negras de los clips (deshabilitablee).

Audio:
    - Opcion 1: Usar el audio que ya trae el clip (si tiene)
    - Opcion 2: Reemplazar con un audio externo (de tools_output/audios/)
    - Solo se escucha UNO de los dos, nunca ambos mezclados.

Navegacion:
    - Al elegir archivos, se navega por carpetas (entrar/salir)
    - Permite organizar material en subcarpetas sin romper nada

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
    python generators/meme_reaction.py
    python generators/meme_reaction.py --config "assets/meme_reaction/configs/meme01.json"
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

SCRIPT_DIR = Path(__file__).parent.parent  # raiz del proyecto (generators/ -> drako-edits/)

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
MAX_CROP_RATIO = 0.30  # Nunca cropear mas del 30% del alto total


# =============================================================================
# NAVEGACION POR CARPETAS
# =============================================================================

def browse_folder(root_dir, extensions, label):
    """
    Navegacion interactiva por carpetas.
    Muestra subcarpetas y archivos del directorio actual.
    Permite entrar a carpetas o elegir un archivo.

    Args:
        root_dir: Directorio raiz (no se puede subir mas arriba de aqui)
        extensions: Set de extensiones validas (ej: {'.jpg', '.png'})
        label: Nombre para mostrar (ej: "imagen", "clip", "audio")

    Returns:
        Path al archivo seleccionado
    """
    if not root_dir.exists():
        print(f"\n   [X] No existe: {root_dir}")
        return None

    current_dir = root_dir

    while True:
        # Obtener carpetas y archivos del nivel actual
        folders = sorted([f for f in current_dir.iterdir() if f.is_dir() and f.name != '.gitkeep'])
        files = sorted([f for f in current_dir.iterdir()
                       if f.is_file() and f.suffix.lower() in extensions])

        # Mostrar ubicacion actual
        try:
            rel_path = current_dir.relative_to(root_dir)
            location = str(rel_path) if str(rel_path) != "." else "(raiz)"
        except ValueError:
            location = current_dir.name

        print(f"\n   --- {label.upper()} ---")
        print(f"   Ubicacion: {root_dir.name}/{location}")

        if not folders and not files:
            print(f"   (vacio)")
            if current_dir == root_dir:
                return None
            # Volver automaticamente
            current_dir = current_dir.parent
            continue

        # Numerar items: carpetas primero, luego archivos
        items = []  # lista de (tipo, path)
        idx = 1

        if folders:
            for folder in folders:
                # Contar archivos dentro (recursivo) para dar contexto
                count = len([f for f in folder.rglob("*") if f.suffix.lower() in extensions])
                print(f"      {idx}. [>] {folder.name}/ ({count} {label}s)")
                items.append(("folder", folder))
                idx += 1

        if files:
            for f in files:
                print(f"      {idx}. {f.name}")
                items.append(("file", f))
                idx += 1

        # Opcion de volver
        if current_dir != root_dir:
            print(f"      0. <- Volver")

        # Input
        while True:
            choice = input(f"\n   Elegir {label} (numero): ").strip()

            if choice == "0" and current_dir != root_dir:
                current_dir = current_dir.parent
                break

            if choice.isdigit():
                chosen_idx = int(choice) - 1
                if 0 <= chosen_idx < len(items):
                    item_type, item_path = items[chosen_idx]
                    if item_type == "folder":
                        current_dir = item_path
                        break
                    else:
                        # Archivo seleccionado
                        return item_path

            print("   [!] No valido.")


# =============================================================================
# FUNCIONES UTILITARIAS
# =============================================================================

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


def detect_black_bars_multiframe(video_clip):
    """
    Detecta barras negras muestreando multiples frames.
    Toma el MINIMO crop de todos los samples (mas conservador).
    Si un frame no tiene barras, no cropea.
    Protege contra fade-ins/frames negros al inicio.
    """
    clip_duration = video_clip.duration
    height = video_clip.size[1]

    # Muestrear en 3 puntos: 25%, 50%, 75% de la duracion
    sample_times = [
        clip_duration * 0.25,
        clip_duration * 0.50,
        clip_duration * 0.75,
    ]

    best_top = height  # empezar con max (peor caso)
    best_bottom = height

    for t in sample_times:
        safe_t = min(t, clip_duration - 0.1)
        if safe_t < 0:
            safe_t = 0
        frame = video_clip.get_frame(safe_t)
        top, bottom = detect_black_bars(frame)
        # Tomar el MINIMO (mas conservador)
        best_top = min(best_top, top)
        best_bottom = min(best_bottom, bottom)

    # Safety: nunca cropear mas del MAX_CROP_RATIO del alto total
    max_crop_px = int(height * MAX_CROP_RATIO)
    if best_top + best_bottom > max_crop_px:
        return 0, 0

    return best_top, best_bottom


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
        "auto_crop": config.get("auto_crop", True),
    }

    return resolved


def save_config(name, meme_path, clip_path, music_path, caption_text, caption_size_key, auto_crop=True):
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
        "auto_crop": auto_crop,
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

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.m4a', '.aac'}


def select_image():
    """Navega tools_output/posts/ para elegir una imagen."""
    result = browse_folder(IMAGES_DIR, IMAGE_EXTENSIONS, "imagen")
    if result is None:
        print(f"\n   [X] No hay imagenes en {IMAGES_DIR}")
        print(f"       Descarga posts con: python tools/instagram/posts_nologin.py")
        sys.exit(1)
    return result


def select_clip():
    """Navega tools_output/videos/ para elegir un clip."""
    result = browse_folder(VIDEOS_DIR, VIDEO_EXTENSIONS, "clip")
    if result is None:
        print(f"\n   [X] No hay videos en {VIDEOS_DIR}")
        print(f"       Descarga clips con: python tools/youtube/download_video_yt.py")
        sys.exit(1)
    return result


def select_audio(clip_path):
    """
    Pregunta que audio usar. Solo se escucha UNO:
      - Audio del clip (si el video lo tiene)
      - Audio externo (reemplaza el del clip)

    Retorna: Path al audio externo, o None para usar audio del clip.
    """
    # Detectar si el clip fue descargado sin audio
    clip_sin_audio = "(sinaudio)" in clip_path.name.lower()

    print(f"\n   --- AUDIO ---")
    print(f"   (Solo se escucha UNO, nunca ambos mezclados)")

    if clip_sin_audio:
        print(f"   [!] El clip '{clip_path.name}' fue descargado SIN audio.")
        # Intentar navegar audios
        result = browse_folder(AUDIOS_DIR, AUDIO_EXTENSIONS, "audio")
        if result is None:
            print(f"   [!] No hay audios en {AUDIOS_DIR}. El video sera MUDO.")
            print(f"       Descarga audio con: python tools/youtube/download_audio_yt.py")
            return None
        print(f"   -> Audio: {result.name} (externo)")
        return result
    else:
        print(f"\n   Fuente de audio:")
        print(f"      1. Usar audio del clip (el que ya trae el video)")
        print(f"      2. Elegir audio externo (de tools_output/audios/)")

        while True:
            choice = input("\n   Opcion (1/2): ").strip()
            if choice == "1" or choice == "":
                print(f"   -> Audio: del clip")
                return None
            if choice == "2":
                break
            print("   [!] No valido.")

        # Navegar audios
        result = browse_folder(AUDIOS_DIR, AUDIO_EXTENSIONS, "audio")
        if result is None:
            print(f"   [!] No hay audios. Usando audio del clip.")
            return None
        print(f"   -> Audio: {result.name} (reemplaza audio del clip)")
        return result


def select_auto_crop():
    """Pregunta si remover barras negras automaticamente."""
    print(f"\n   --- AUTO-CROP ---")
    print(f"   Remover barras negras del clip automaticamente?")
    print(f"      s = Si (detecta y remueve letterboxing)")
    print(f"      n = No (dejar el clip tal cual)")
    choice = input("   Auto-crop (s/n, default s): ").strip().lower()
    if choice == "n" or choice == "no":
        print(f"   -> Auto-crop: DESHABILITADO")
        return False
    print(f"   -> Auto-crop: habilitado")
    return True


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

def generate_video(meme_path, clip_path, music_path, caption_text, caption_size_key, output_name=None, auto_crop=True):
    """Genera el video de meme reaction."""
    caption_size = CAPTION_SIZES.get(caption_size_key, CAPTION_SIZES["M"]) if caption_size_key else None

    print(f"\n{'='*50}")
    print(f"   GENERANDO MEME REACTION")
    print(f"   Meme:    {meme_path.name}")
    print(f"   Clip:    {clip_path.name}")
    if music_path:
        print(f"   Audio:   {music_path.name} (externo)")
    else:
        print(f"   Audio:   del clip")
    print(f"   Caption: {caption_text or '(sin)'} [{caption_size_key or '-'}]")
    print(f"   Crop:    {'auto' if auto_crop else 'deshabilitado'}")
    print(f"{'='*50}")

    # Cargar clip
    print("\n   Cargando clip...")
    video_clip = VideoFileClip(str(clip_path))

    # Auto-detectar barras negras (solo si habilitado)
    if auto_crop:
        top_crop, bottom_crop = detect_black_bars_multiframe(video_clip)

        if top_crop > 0 or bottom_crop > 0:
            orig_h = video_clip.size[1]
            print(f"   [auto-crop] Barras: top={top_crop}px, bottom={bottom_crop}px")
            video_clip = video_clip.cropped(
                x1=0, y1=top_crop,
                x2=video_clip.size[0], y2=video_clip.size[1] - bottom_crop
            )
            print(f"   [auto-crop] {orig_h}px -> {video_clip.size[1]}px")
        else:
            print(f"   [auto-crop] Sin barras negras")
    else:
        print(f"   [auto-crop] Deshabilitado")

    clip_size = video_clip.size

    # Layout dinamico
    meme_area_h, clip_area_h = calculate_layout(meme_path, clip_size)
    print(f"   Layout: meme={meme_area_h}px ({meme_area_h/VIDEO_HEIGHT*100:.0f}%) | clip={clip_area_h}px")

    # Preparar meme
    print("   Procesando meme...")
    meme_img = Image.open(meme_path).convert("RGB")
    meme_fitted = fit_image_to_area(meme_img, VIDEO_WIDTH, meme_area_h)
    meme_array = np.array(meme_fitted)

    # Duracion y audio
    if music_path:
        # Audio externo: reemplaza completamente el audio del clip
        audio_clip = AudioFileClip(str(music_path))
        duration = min(video_clip.duration, audio_clip.duration)
    else:
        # Audio del clip: usa lo que trae el video
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

    # Audio (solo UNO)
    if audio_clip:
        # Audio externo seleccionado -> ignorar audio del clip
        audio_clip = audio_clip.subclipped(0, min(duration, audio_clip.duration - 0.01))
        final = final.with_audio(audio_clip)
        print(f"   Audio: externo ({music_path.name})")
    elif video_clip.audio:
        # Usar audio que trae el clip
        final = final.with_audio(video_clip.audio)
        print(f"   Audio: del clip")
    else:
        print(f"   Audio: (sin audio - video mudo)")

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
            print(f"   [!] Audio externo no encontrado: {config['music']}. Usando audio del clip.")
            config["music"] = None

        generate_video(
            config["meme"], config["clip"], config["music"],
            config["caption"], config["caption_size"],
            config["name"], auto_crop=config["auto_crop"]
        )

    else:
        # === MODO MANUAL ===
        # 1. Imagen
        meme_path = select_image()
        print(f"   -> Imagen: {meme_path.name}")

        # 2. Clip
        clip_path = select_clip()
        print(f"   -> Clip: {clip_path.name}")

        # 3. Audio (del clip o externo, solo UNO)
        music_path = select_audio(clip_path)

        # 4. Auto-crop
        auto_crop = select_auto_crop()

        # 5. Caption
        caption_text, caption_size_key = select_caption()

        # 6. Nombre
        output_name = input("\n   Nombre del video (sin .mp4, Enter=auto): ").strip()
        if not output_name:
            output_name = None

        # 7. Generar
        generate_video(meme_path, clip_path, music_path, caption_text, caption_size_key,
                       output_name, auto_crop=auto_crop)

        # 8. Guardar como config?
        save_choice = input("\n   Guardar esta combinacion como JSON config? (s/n): ").strip().lower()
        if save_choice == "s":
            config_name = input("   Nombre del config: ").strip()
            if not config_name:
                config_name = output_name or f"meme_{meme_path.stem}_{clip_path.stem}"
            save_config(config_name, meme_path, clip_path, music_path,
                        caption_text, caption_size_key, auto_crop)

    print("\n>>> Done!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Drako Edits - Meme Reaction Generator")
    parser.add_argument("--config", type=str, default=None,
                        help="Path a un JSON config para generar directamente")
    parser.add_argument("--no-crop", action="store_true",
                        help="Deshabilitar auto-crop de barras negras")
    args = parser.parse_args()

    if args.config:
        config = load_config(args.config)
        if not config["meme"].exists():
            print(f"[X] Meme no encontrado: {config['meme']}")
            sys.exit(1)
        if not config["clip"].exists():
            print(f"[X] Clip no encontrado: {config['clip']}")
            sys.exit(1)
        # --no-crop override el config JSON
        auto_crop = config["auto_crop"] if not args.no_crop else False
        generate_video(
            config["meme"], config["clip"], config["music"],
            config["caption"], config["caption_size"],
            config["name"], auto_crop=auto_crop
        )
    else:
        main()
