#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 7: Generacion de Video (Meme Reaction)

Toma los memes matcheados (paso 4) y genera videos usando la logica del generator.
Por cada match:
  - Meme: memes_descargados/{shortcode}.jpg (con crop de franjas PROGRAMATICO)
  - Clip: clips/{clip_id}.mp4 (copia local catalogada)
  - Audio: SIEMPRE del clip (no se puede elegir audio externo en automatizacion)
  - Caption: del match (paso 4)
  - Auto-crop clip: habilitado (barras negras del clip)

Deteccion de franjas negras del meme: PROGRAMATICA (escanea pixels reales).
NO depende de la clasificacion IA (detail:low es impreciso para bordes).

Tambien genera el JSON config (paso 8) automaticamente.

Layout:
  - Meme: arriba, maximo 70% de pantalla, con borde/padding de 3% en todos los lados
  - Clip: abajo, maximo 40% de pantalla, sin borde
  - El meme SIEMPRE se ve completo (fit, nunca crop)
  - Si meme es chico, se centra en su zona con fondo de relleno

Modo semi-interactivo:
  - Muestra cada match antes de generar
  - Puedes confirmar, saltar, o salir
  - Flag --auto para generar todo sin preguntar

Uso:
    python 7_generate_video.py              # Interactivo (confirma cada uno)
    python 7_generate_video.py --auto       # Genera todo sin preguntar
    python 7_generate_video.py --max 3      # Solo 3 videos
    python 7_generate_video.py --redo ABC123          # Re-generar uno
    python 7_generate_video.py --redo ABC123 DEF456   # Re-generar varios
    python 7_generate_video.py --redo-all             # Re-generar todos
    python 7_generate_video.py --no-crop-meme         # No cropear franjas del meme

Dependencias: moviepy, Pillow, numpy
"""

import json
import sys
import io
import os
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

try:
    from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip
except ImportError:
    print("   [X] Necesitas instalar moviepy:")
    print("       pip install moviepy")
    sys.exit(1)

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # drako-edits/
HISTORIAL_DIR = SCRIPT_DIR / "historial"
MATCHES_FILE = HISTORIAL_DIR / "matches.json"
CLASIFICACIONES_FILE = HISTORIAL_DIR / "clasificaciones.json"
CATALOGO_FILE = SCRIPT_DIR / "catalogo_clips.json"
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
CLIPS_DIR = SCRIPT_DIR / "clips"
CONFIGS_DIR = SCRIPT_DIR / "configs_generados"
OUTPUT_DIR = PROJECT_ROOT / "output" / "meme_reaction"
GENERATED_FILE = HISTORIAL_DIR / "generados.json"

# Video config (mismos valores que generators/meme_reaction.py)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# =============================================================================
# LAYOUT PROPORTIONS
# =============================================================================
# Clip: siempre abajo, maximo 40% de pantalla, sin borde
# Meme: siempre arriba, maximo 70% de pantalla, con borde de 3%
# Si meme es chico (ej. cabe en 30%), clip sigue en 40% y meme se centra
# en el 60% restante con padding de fondo.
# Si meme necesita mas (>60%), expande hasta 70% y clip baja a 30%.

CLIP_MAX_RATIO = 0.40       # Clip toma maximo 40% de la pantalla
CLIP_MIN_RATIO = 0.30       # Clip minimo 30% (cuando meme necesita 70%)
MEME_MAX_RATIO = 0.70       # Zona meme maximo 70% de la pantalla
MEME_BORDER_RATIO = 0.03    # 3% de padding en cada lado del meme

# Background color (default blanco, puede cambiar por clasificacion)
BG_COLOR_MAP = {
    "negro": (0, 0, 0),
    "blanco": (255, 255, 255),
    "otro": (255, 255, 255),
}

# Font config
STROKE_WIDTH = 4
CAPTION_SIZES = {
    "S": 45,
    "M": 65,
    "L": 85,
    "XL": 110,
}

# Auto-crop config (para barras negras de MEME y CLIP)
BLACK_BAR_THRESHOLD = 15    # Mean pixel value debajo de esto = "negro"
BLACK_BAR_MIN_ROWS = 8      # Minimo de filas para considerar "franja" (no ruido)
MAX_CROP_RATIO = 0.30       # Nunca cropear mas del 30% del alto total

MAX_POR_SESION = 10


# =============================================================================
# FUNCIONES - CARGA DE DATOS
# =============================================================================

def load_matches():
    if MATCHES_FILE.exists():
        try:
            return json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"matched": [], "skipped_buscar_clip": []}


def load_clasificaciones():
    if CLASIFICACIONES_FILE.exists():
        try:
            return json.loads(CLASIFICACIONES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clasificados": []}


def load_catalogo():
    if CATALOGO_FILE.exists():
        try:
            return json.loads(CATALOGO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clips": []}


def load_generados():
    if GENERATED_FILE.exists():
        try:
            return json.loads(GENERATED_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"generados": [], "errores": []}


def save_generados(data):
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_clasificacion(shortcode, clasificaciones):
    """Busca la clasificacion de un meme por shortcode."""
    for item in clasificaciones.get("clasificados", []):
        if item["shortcode"] == shortcode:
            return item
    return None


def get_clip_info(clip_id, catalogo):
    """Busca info del clip en el catalogo."""
    for clip in catalogo.get("clips", []):
        if clip["id"] == clip_id:
            return clip
    return None


def get_pending_generations(matches, generados):
    """Matches que tienen clip_id y aun no se han generado."""
    already = {item["shortcode"] for item in generados.get("generados", [])}
    already.update(item["shortcode"] for item in generados.get("errores", []))

    pending = []
    for match in matches.get("matched", []):
        if match["shortcode"] not in already and match.get("clip_id"):
            pending.append(match)
    return pending


# =============================================================================
# FUNCIONES - REDO (Re-generar videos)
# =============================================================================

def remove_from_generados(generados, shortcodes):
    """
    Remueve shortcodes de generados y errores para que vuelvan a ser 'pendientes'.
    Retorna cuantos se removieron.
    """
    removed = 0
    shortcodes_set = set(shortcodes)

    original_gen = len(generados.get("generados", []))
    generados["generados"] = [
        item for item in generados.get("generados", [])
        if item["shortcode"] not in shortcodes_set
    ]
    removed += original_gen - len(generados["generados"])

    original_err = len(generados.get("errores", []))
    generados["errores"] = [
        item for item in generados.get("errores", [])
        if item["shortcode"] not in shortcodes_set
    ]
    removed += original_err - len(generados["errores"])

    return removed


# =============================================================================
# FUNCIONES - DETECCION PROGRAMATICA DE BARRAS NEGRAS
# =============================================================================

def detect_black_bars_image(image_path):
    """
    Detecta barras negras arriba y abajo de una IMAGEN (meme) por pixels reales.
    NO depende de la IA - escanea directamente los valores de pixel.
    Retorna (top_pixels, bottom_pixels) a cropear.
    """
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img)
    height = arr.shape[0]

    row_means = np.mean(arr, axis=(1, 2))

    top_crop = 0
    for row in range(height):
        if row_means[row] < BLACK_BAR_THRESHOLD:
            top_crop = row + 1
        else:
            break

    bottom_crop = 0
    for row in range(height - 1, -1, -1):
        if row_means[row] < BLACK_BAR_THRESHOLD:
            bottom_crop = height - row
        else:
            break

    if top_crop < BLACK_BAR_MIN_ROWS:
        top_crop = 0
    if bottom_crop < BLACK_BAR_MIN_ROWS:
        bottom_crop = 0

    if top_crop + bottom_crop > int(height * MAX_CROP_RATIO):
        return 0, 0

    return top_crop, bottom_crop


def detect_black_bars(frame):
    """Detecta barras negras arriba y abajo de un frame de video."""
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
    """Detecta barras negras del clip muestreando multiples frames."""
    clip_duration = video_clip.duration
    height = video_clip.size[1]

    sample_times = [
        clip_duration * 0.25,
        clip_duration * 0.50,
        clip_duration * 0.75,
    ]

    best_top = height
    best_bottom = height

    for t in sample_times:
        safe_t = min(t, clip_duration - 0.1)
        if safe_t < 0:
            safe_t = 0
        frame = video_clip.get_frame(safe_t)
        top, bottom = detect_black_bars(frame)
        best_top = min(best_top, top)
        best_bottom = min(best_bottom, bottom)

    max_crop_px = int(height * MAX_CROP_RATIO)
    if best_top + best_bottom > max_crop_px:
        return 0, 0

    return best_top, best_bottom


def crop_meme_franjas(meme_path):
    """
    Detecta y cropea franjas negras del meme PROGRAMATICAMENTE.
    Escanea los pixels reales de la imagen - NO depende de la IA.
    Retorna path a imagen cropeada (temp) o la original si no hay crop.
    """
    top_crop, bottom_crop = detect_black_bars_image(meme_path)

    if top_crop == 0 and bottom_crop == 0:
        return meme_path

    img = Image.open(meme_path)
    w, h = img.size

    new_top = top_crop
    new_bottom = h - bottom_crop

    if new_top >= new_bottom:
        return meme_path

    cropped = img.crop((0, new_top, w, new_bottom))

    temp_path = meme_path.parent / f"_temp_crop_{meme_path.name}"
    cropped.save(temp_path, quality=95)

    top_pct = top_crop / h * 100
    bot_pct = bottom_crop / h * 100
    print(f"   [meme-crop] Franjas: top={top_crop}px ({top_pct:.0f}%), bottom={bottom_crop}px ({bot_pct:.0f}%)")
    print(f"   [meme-crop] {h}px -> {new_bottom - new_top}px")

    return temp_path


# =============================================================================
# FUNCIONES - LAYOUT & VIDEO GENERATION
# =============================================================================

def find_font():
    """Busca una fuente bold disponible en el sistema."""
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


def fit_image_to_area(img, area_width, area_height, bg_color=(255, 255, 255)):
    """
    Escala imagen para que quepa completa (fit, no crop).
    Rellena con bg_color. Centra la imagen en el area.
    """
    img_ratio = img.width / img.height
    area_ratio = area_width / area_height

    if img_ratio > area_ratio:
        new_w = area_width
        new_h = int(area_width / img_ratio)
    else:
        new_h = area_height
        new_w = int(area_height * img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    canvas = Image.new("RGB", (area_width, area_height), bg_color)
    x = (area_width - new_w) // 2
    y = (area_height - new_h) // 2
    canvas.paste(img, (x, y))
    return canvas


def calculate_layout(meme_path, clip_size):
    """
    Calcula split dinamico meme/clip.

    Reglas:
    - Clip: maximo 40%, minimo 30%, SIN borde, siempre abajo
    - Meme: maximo 70%, CON borde de 3% en cada lado, siempre arriba
    - Default: clip 40%, meme_zona 60%
    - Si el meme necesita mas de 60% (por su aspect ratio + bordes): 
      expandir meme hasta 70%, clip baja a 30%
    - El meme SIEMPRE se ve completo (fit dentro de zona - bordes)
    - Si el meme es chico, se centra en su zona con fondo de relleno

    Retorna (meme_area_h, clip_area_h)
    """
    border_y = int(MEME_BORDER_RATIO * VIDEO_HEIGHT)  # ~58px
    border_x = int(MEME_BORDER_RATIO * VIDEO_WIDTH)   # ~32px

    # Calcular alto natural del meme al ancho disponible (dentro de bordes)
    meme_img = Image.open(meme_path)
    meme_ratio = meme_img.width / meme_img.height
    drawable_w = VIDEO_WIDTH - 2 * border_x
    meme_natural_h = int(drawable_w / meme_ratio)  # alto necesario para mostrar meme completo
    meme_needed = meme_natural_h + 2 * border_y    # total con bordes arriba/abajo

    # Default split: clip 40%, meme 60%
    default_clip_h = int(CLIP_MAX_RATIO * VIDEO_HEIGHT)   # 768px
    default_meme_h = VIDEO_HEIGHT - default_clip_h        # 1152px

    if meme_needed <= default_meme_h:
        # El meme cabe comodo en el 60% default
        # Clip toma 40%, meme zona = 60% (meme se centra dentro)
        meme_area_h = default_meme_h
        clip_area_h = default_clip_h
    else:
        # El meme necesita mas espacio - expandir zona meme
        max_meme_h = int(MEME_MAX_RATIO * VIDEO_HEIGHT)   # 1344px
        meme_area_h = min(meme_needed, max_meme_h)
        clip_area_h = VIDEO_HEIGHT - meme_area_h

        # Asegurar que clip no baje de 30%
        min_clip_h = int(CLIP_MIN_RATIO * VIDEO_HEIGHT)    # 576px
        if clip_area_h < min_clip_h:
            clip_area_h = min_clip_h
            meme_area_h = VIDEO_HEIGHT - clip_area_h

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


def auto_caption_size(caption_text):
    """Determina tamano del caption automaticamente segun longitud."""
    if not caption_text:
        return None
    length = len(caption_text.replace("|", ""))
    if length > 60:
        return "S"
    elif length > 30:
        return "M"
    elif length > 15:
        return "L"
    else:
        return "XL"


def generate_meme_reaction(meme_path, clip_path, caption_text, caption_size_key,
                           output_name, bg_color=(255, 255, 255)):
    """
    Genera el video de meme reaction.

    Layout:
    - Meme arriba: zona con borde de 3%, imagen centrada (fit completo)
    - Clip abajo: sin borde, fit al ancho
    - Audio: siempre del clip
    """
    caption_size = CAPTION_SIZES.get(caption_size_key, CAPTION_SIZES["M"]) if caption_size_key else None

    print(f"\n   {'='*50}")
    print(f"   GENERANDO MEME REACTION")
    print(f"   Meme:    {meme_path.name}")
    print(f"   Clip:    {clip_path.name}")
    print(f"   Audio:   del clip")
    print(f"   Caption: {caption_text or '(sin)'} [{caption_size_key or '-'}]")
    print(f"   {'='*50}")

    # --- Cargar clip ---
    print("\n   Cargando clip...")
    video_clip = VideoFileClip(str(clip_path))

    # Auto-crop barras negras del clip
    top_crop, bottom_crop = detect_black_bars_multiframe(video_clip)
    if top_crop > 0 or bottom_crop > 0:
        orig_h = video_clip.size[1]
        print(f"   [clip-crop] Barras: top={top_crop}px, bottom={bottom_crop}px")
        video_clip = video_clip.cropped(
            x1=0, y1=top_crop,
            x2=video_clip.size[0], y2=video_clip.size[1] - bottom_crop
        )
        print(f"   [clip-crop] {orig_h}px -> {video_clip.size[1]}px")
    else:
        print(f"   [clip-crop] Sin barras negras")

    clip_size = video_clip.size

    # --- Layout dinamico ---
    meme_area_h, clip_area_h = calculate_layout(meme_path, clip_size)
    print(f"   Layout: meme_zona={meme_area_h}px ({meme_area_h/VIDEO_HEIGHT*100:.0f}%) | clip={clip_area_h}px ({clip_area_h/VIDEO_HEIGHT*100:.0f}%)")

    # --- Preparar meme (con borde, centrado, fit completo) ---
    print("   Procesando meme...")
    border_y = int(MEME_BORDER_RATIO * VIDEO_HEIGHT)  # padding vertical (~58px)
    border_x = int(MEME_BORDER_RATIO * VIDEO_WIDTH)   # padding horizontal (~32px)
    drawable_w = VIDEO_WIDTH - 2 * border_x
    drawable_h = meme_area_h - 2 * border_y

    meme_img = Image.open(meme_path).convert("RGB")

    # Fit meme dentro del area dibujable (nunca crop, siempre completo)
    meme_fitted = fit_image_to_area(meme_img, drawable_w, drawable_h, bg_color)

    # Crear canvas completo de la zona meme (bg + meme centrado con bordes)
    meme_canvas = Image.new("RGB", (VIDEO_WIDTH, meme_area_h), bg_color)
    meme_canvas.paste(meme_fitted, (border_x, border_y))
    meme_array = np.array(meme_canvas)

    print(f"   [meme] Imagen: {meme_img.width}x{meme_img.height} -> fit en {drawable_w}x{drawable_h} (borde {border_x}px/{border_y}px)")

    # --- Duracion = duracion del clip ---
    duration = video_clip.duration
    print(f"   Duracion: {duration:.2f}s")

    video_clip = video_clip.subclipped(0, min(duration, video_clip.duration - 0.01))

    # --- Procesar frames del clip (fit al area, sin borde) ---
    def process_frame(frame):
        img = Image.fromarray(frame)
        fitted = fit_image_to_area(img, VIDEO_WIDTH, clip_area_h, bg_color)
        return np.array(fitted)

    print("   Procesando frames...")
    processed_clip = video_clip.image_transform(process_frame)

    # --- Composicion ---
    meme_clip = ImageClip(meme_array).with_duration(duration)
    meme_clip = meme_clip.with_position((0, 0))
    processed_clip = processed_clip.with_position((0, meme_area_h))

    layers = [meme_clip, processed_clip]

    # Caption (se posiciona entre meme y clip)
    if caption_text and caption_size:
        font_path = find_font()
        caption_img = render_caption(caption_text, font_path, caption_size)
        x_pos = max(0, (VIDEO_WIDTH - caption_img.shape[1]) // 2)
        # Caption en la linea divisoria meme/clip
        y_pos = meme_area_h - caption_img.shape[0] // 2
        cap_clip = (ImageClip(caption_img)
                    .with_position((x_pos, y_pos))
                    .with_duration(duration))
        layers.append(cap_clip)

    # Componer
    print("   Componiendo...")
    final = CompositeVideoClip(layers, size=(VIDEO_WIDTH, VIDEO_HEIGHT))
    final = final.with_duration(duration)

    # Audio del clip
    if video_clip.audio:
        final = final.with_audio(video_clip.audio)
        print(f"   Audio: del clip")
    else:
        print(f"   Audio: (clip sin audio - video mudo)")

    # Export
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{output_name}.mp4"

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

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\n   [OK] Video: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# =============================================================================
# FUNCIONES - CONFIG JSON (Paso 8)
# =============================================================================

def save_config_json(shortcode, match_data, clasificacion, clip_info, output_path, caption_size_key):
    """Guarda JSON config para poder replicar/editar manualmente despues."""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    config = {
        "shortcode": shortcode,
        "meme_path": f"automatizaciones/Meme_Reaction/memes_descargados/{shortcode}.jpg",
        "clip_path": f"automatizaciones/Meme_Reaction/clips/{match_data.get('clip_id')}.mp4",
        "clip_id": match_data.get("clip_id"),
        "caption": match_data.get("caption"),
        "caption_size": caption_size_key,
        "categorias": clasificacion.get("categorias", []) if clasificacion else [],
        "accuracy": match_data.get("accuracy", 0),
        "audio_source": "clip",
        "auto_crop_clip": True,
        "auto_crop_meme": True,
        "background_color": clasificacion.get("background_color", "blanco") if clasificacion else "blanco",
        "output_name": output_path.name if output_path else None,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "auto_generated": True,
        "conversacion": match_data.get("conversacion", False),
    }

    config_file = CONFIGS_DIR / f"{shortcode}.json"
    config_file.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"   [OK] Config: {config_file.name}")
    return config_file


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def main():
    parser = argparse.ArgumentParser(description="Paso 7: Generar videos de meme reaction")
    parser.add_argument("--max", type=int, default=MAX_POR_SESION,
                        help=f"Maximo de videos a generar (default: {MAX_POR_SESION})")
    parser.add_argument("--auto", action="store_true",
                        help="Generar todo sin preguntar")
    parser.add_argument("--redo", nargs="+", metavar="SHORTCODE",
                        help="Re-generar video(s) especifico(s) por shortcode")
    parser.add_argument("--redo-all", action="store_true",
                        help="Re-generar TODOS los videos (limpia historial completo)")
    parser.add_argument("--no-crop-meme", action="store_true",
                        help="No cropear franjas negras del meme (usar imagen original)")
    args = parser.parse_args()

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 7: GENERAR VIDEOS")
    print(SEPARATOR_EQ)
    print(f"   Output: {OUTPUT_DIR}")
    print(f"   Configs: {CONFIGS_DIR}")
    if args.auto:
        print("   Modo: AUTOMATICO (sin confirmacion)")
    else:
        print("   Modo: INTERACTIVO (confirma cada uno)")
    if args.no_crop_meme:
        print("   Crop meme: DESHABILITADO (imagen original)")
    print(SEPARATOR_EQ)

    # Cargar datos
    matches = load_matches()
    clasificaciones = load_clasificaciones()
    catalogo = load_catalogo()
    generados = load_generados()

    # --- REDO: remover de generados para que vuelvan a ser pendientes ---
    if args.redo_all:
        total = len(generados.get("generados", [])) + len(generados.get("errores", []))
        generados["generados"] = []
        generados["errores"] = []
        save_generados(generados)
        print(f"\n   [REDO-ALL] Limpiado historial completo ({total} entradas).")
        print(f"   Todos los matches vuelven a ser pendientes.")
    elif args.redo:
        removed = remove_from_generados(generados, args.redo)
        save_generados(generados)
        if removed > 0:
            print(f"\n   [REDO] Removidos {removed} de generados/errores:")
            for sc in args.redo:
                print(f"          - {sc}")
        else:
            print(f"\n   [REDO] Ningun shortcode encontrado en generados/errores:")
            for sc in args.redo:
                print(f"          - {sc} (no estaba)")

    # Obtener pendientes
    pending = get_pending_generations(matches, generados)

    if not pending:
        print(f"\n   [!] No hay videos pendientes de generar.")
        print(f"       Matched con clip: {sum(1 for m in matches.get('matched', []) if m.get('clip_id'))}")
        print(f"       Ya generados: {len(generados.get('generados', []))}")
        print(f"       Sin clip asignado: {sum(1 for m in matches.get('matched', []) if not m.get('clip_id'))}")
        return

    batch = pending[:args.max]
    print(f"\n   Pendientes: {len(pending)}")
    print(f"   Procesando: {len(batch)}")

    # Stats
    stats = {"generados": 0, "skipped": 0, "errores": 0}

    for i, match_data in enumerate(batch):
        shortcode = match_data["shortcode"]
        clip_id = match_data["clip_id"]
        caption = match_data.get("caption")
        accuracy = match_data.get("accuracy", 0)

        # Buscar archivos
        meme_path = MEMES_DIR / f"{shortcode}.jpg"
        clip_info = get_clip_info(clip_id, catalogo)
        clasificacion = get_clasificacion(shortcode, clasificaciones)

        if not clip_info:
            print(f"\n   [X] Clip '{clip_id}' no encontrado en catalogo. Saltando {shortcode}.")
            generados["errores"].append({
                "shortcode": shortcode, "error": f"clip {clip_id} no en catalogo",
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_generados(generados)
            stats["errores"] += 1
            continue

        clip_filename = clip_info.get("filename", f"{clip_id}.mp4")
        clip_path = CLIPS_DIR / clip_filename

        if not meme_path.exists():
            print(f"\n   [X] Meme no encontrado: {meme_path.name}. Saltando.")
            generados["errores"].append({
                "shortcode": shortcode, "error": "meme no encontrado",
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_generados(generados)
            stats["errores"] += 1
            continue

        if not clip_path.exists():
            print(f"\n   [X] Clip no encontrado: {clip_path.name}. Saltando.")
            generados["errores"].append({
                "shortcode": shortcode, "error": f"archivo {clip_filename} no existe",
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_generados(generados)
            stats["errores"] += 1
            continue

        # Mostrar info
        print(f"\n{SEPARATOR}")
        print(f"   [{i+1}/{len(batch)}] {shortcode}")
        print(f"       Clip: {clip_id} - \"{clip_info.get('descripcion', '?')[:60]}\"")
        print(f"       Accuracy: {accuracy}%")
        if caption:
            print(f"       Caption: \"{caption}\"")
        else:
            print(f"       Caption: (sin caption)")
        if clasificacion:
            cats = ", ".join(clasificacion.get("categorias", []))
            bg = clasificacion.get("background_color", "blanco")
            print(f"       Categorias: {cats}")
            print(f"       Background: {bg}")
        print(SEPARATOR)

        # Confirmar (a menos que sea --auto)
        if not args.auto:
            choice = input("       Generar? (Enter/s=si, n=skip, q=salir): ").strip().lower()
            if choice in ('n', 'no', 'skip'):
                stats["skipped"] += 1
                print("       -> SKIP")
                continue
            elif choice in ('q', 'quit', 'salir'):
                print("\n   [SALIR] Progreso guardado.")
                break

        # Crop franjas negras del meme (a menos que --no-crop-meme)
        if not args.no_crop_meme:
            actual_meme_path = crop_meme_franjas(meme_path)
        else:
            actual_meme_path = meme_path
            print("   [meme-crop] Skipped (--no-crop-meme)")

        # Determinar background color
        bg_key = clasificacion.get("background_color", "blanco") if clasificacion else "blanco"
        bg_color = BG_COLOR_MAP.get(bg_key, (255, 255, 255))

        # Caption size
        caption_size_key = auto_caption_size(caption)

        # Output name
        output_name = f"meme_{shortcode}_{clip_id}"

        # Generar
        try:
            output_path = generate_meme_reaction(
                meme_path=actual_meme_path,
                clip_path=clip_path,
                caption_text=caption,
                caption_size_key=caption_size_key,
                output_name=output_name,
                bg_color=bg_color
            )

            # Guardar en historial
            generados["generados"].append({
                "shortcode": shortcode,
                "clip_id": clip_id,
                "caption": caption,
                "output": output_path.name,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_generados(generados)

            # Guardar config JSON (paso 8)
            save_config_json(shortcode, match_data, clasificacion, clip_info,
                             output_path, caption_size_key)

            stats["generados"] += 1

        except Exception as e:
            print(f"\n   [X] ERROR generando {shortcode}: {str(e)[:200]}")
            generados["errores"].append({
                "shortcode": shortcode, "error": str(e)[:200],
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_generados(generados)
            stats["errores"] += 1

        finally:
            # Limpiar temp crop si se creo
            if actual_meme_path != meme_path and actual_meme_path.exists():
                actual_meme_path.unlink()

    # Resumen
    print(f"\n{SEPARATOR_EQ}")
    print("   RESUMEN")
    print(SEPARATOR_EQ)
    print(f"   Videos generados: {stats['generados']}")
    print(f"   Skipped: {stats['skipped']}")
    print(f"   Errores: {stats['errores']}")
    print(f"")
    print(f"   TOTALES:")
    print(f"     Total generados: {len(generados.get('generados', []))}")
    print(f"     Total errores: {len(generados.get('errores', []))}")
    print(f"   Videos en: {OUTPUT_DIR}")
    print(f"   Configs en: {CONFIGS_DIR}")
    print(SEPARATOR_EQ)


if __name__ == "__main__":
    main()
