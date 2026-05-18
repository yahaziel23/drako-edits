#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador Generico con Videos (Interactivo + JSON rapido)

Genera videos compuestos: audio + clips de video por tramo + subtitulos.
Igual que generate_generic pero usando clips de video en vez de imagenes.
Soporta configuracion paso a paso O carga rapida desde JSON.

Uso:
    python generate_video_generic.py                    # Interactivo (paso a paso)
    python generate_video_generic.py --json config.json # Config rapida desde archivo

Estructura requerida:
    assets/video_generic/
        audio/          <- audios disponibles
        videos/         <- clips de video disponibles
        output/         <- videos generados
        configs/        <- JSONs guardados para reusar

Formato del JSON:
    {
        "audio": "cancion.mp3",
        "output_name": "mi_video",
        "background": "blur",
        "fill_mode": "cover",
        "segments": [
            {"end": 3.5, "video": "clip1.mp4", "video_start": 0, "subtitle": "Texto..."},
            {"end": 7.0, "video": "clip2.mp4", "video_start": 2.5, "subtitle": "same"},
            {"end": "ultimo", "video": "clip3.mp4", "video_start": 0, "subtitle": null}
        ]
    }

    Reglas del JSON:
    - "background": "white", "black", o "blur" (frame del video borroso de fondo)
    - "fill_mode": "cover" (cubre todo, puede cortar) o "fit" (completo, con fondo)
    - "video": nombre del archivo de video en la carpeta videos/
    - "video_start": segundo donde empieza el clip (default 0)
    - "subtitle": texto, "same" (mismo que anterior), o null (sin subtitulo)
    - "subtitle": usa | para salto de linea (ej. "hola|mundo" -> dos lineas)
    - "subtitle": usa ^ al inicio para subir o v para bajar (ej. "^^texto" sube 2 pasos)
    - "end": numero (timestamp) o "ultimo" (hasta el final del audio)

Nota: Solo se muestran videos cuya duracion sea >= la duracion del segmento.
      El video se recorta automaticamente al final del segmento.
      Puedes elegir desde que segundo empieza el video (gap = duracion_video - duracion_segmento).
"""

import os
import sys
import io
import json
import subprocess
import argparse
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip
from mutagen import File as MutagenFile

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "video_generic"

AUDIO_DIR = ASSETS_DIR / "audio"
VIDEOS_DIR = ASSETS_DIR / "videos"
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
SUBTITLE_Y_STEP = 80  # Pixeles por cada ^ (subir) o v (bajar)

# Blur background config
BLUR_RADIUS = 30
BLUR_OPACITY = 0.4  # 0=invisible, 1=fully visible

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}


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


def get_video_duration(video_path):
    """Obtiene la duracion de un video usando ffprobe (rapido)."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    # Fallback: moviepy
    try:
        clip = VideoFileClip(str(video_path))
        dur = clip.duration
        clip.close()
        return dur
    except Exception:
        return None


def get_videos_from_dir(directory):
    """Obtiene todos los videos de un directorio."""
    if not directory.exists():
        return []
    vids = [f for f in directory.iterdir() if f.suffix.lower() in VIDEO_EXTENSIONS]
    return sorted(vids)


def format_time(seconds):
    """Formatea segundos a MM:SS.ms legible."""
    mins = int(seconds) // 60
    secs = seconds - (mins * 60)
    if mins > 0:
        return f"{mins}:{secs:05.2f}"
    return f"{secs:.3f}s"


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


def parse_subtitle_position(text):
    """
    Extrae modificadores de posicion del subtitulo.
    ^ al inicio = subir (cada ^ sube SUBTITLE_Y_STEP px)
    v al inicio = bajar (cada v baja SUBTITLE_Y_STEP px)
    Retorna (texto_limpio, y_offset).
    """
    offset = 0
    while text.startswith("^"):
        offset -= SUBTITLE_Y_STEP
        text = text[1:]
    while text.startswith("v"):
        offset += SUBTITLE_Y_STEP
        text = text[1:]
    return text.strip(), offset


def render_subtitle(text, font_path):
    """Renderiza subtitulo centrado con stroke negro. Usa | para salto de linea."""
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


def process_video_frame(frame, fill_mode, background):
    """
    Procesa un frame de video segun el modo elegido.
    Retorna numpy array RGB de VIDEO_WIDTH x VIDEO_HEIGHT.
    """
    img = Image.fromarray(frame).convert("RGB")
    target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT
    img_ratio = img.width / img.height

    if fill_mode == "cover":
        # Cubrir todo (puede cortar)
        if img_ratio > target_ratio:
            new_h = VIDEO_HEIGHT
            new_w = int(new_h * img_ratio)
        else:
            new_w = VIDEO_WIDTH
            new_h = int(new_w / img_ratio)

        img = img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - VIDEO_WIDTH) // 2
        top = (new_h - VIDEO_HEIGHT) // 2
        img = img.crop((left, top, left + VIDEO_WIDTH, top + VIDEO_HEIGHT))
        return np.array(img)

    else:  # fit
        # Mostrar completo (con fondo)
        if img_ratio > target_ratio:
            new_w = VIDEO_WIDTH
            new_h = int(VIDEO_WIDTH / img_ratio)
        else:
            new_h = VIDEO_HEIGHT
            new_w = int(VIDEO_HEIGHT * img_ratio)

        img_fitted = img.resize((new_w, new_h), Image.LANCZOS)

        if background == "blur":
            # Fondo = mismo frame escalado + blur + oscurecido
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
            dark = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))
            canvas = Image.blend(dark, bg, BLUR_OPACITY)
        elif background == "white":
            canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (255, 255, 255))
        else:  # black
            canvas = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0))

        x = (VIDEO_WIDTH - new_w) // 2
        y = (VIDEO_HEIGHT - new_h) // 2
        canvas.paste(img_fitted, (x, y))
        return np.array(canvas)


# =============================================================================
# CACHE DE DURACIONES
# =============================================================================

_duration_cache = {}

def get_cached_duration(video_path):
    """Obtiene duracion con cache para no recalcular."""
    key = str(video_path)
    if key not in _duration_cache:
        _duration_cache[key] = get_video_duration(video_path)
    return _duration_cache[key]


def preload_durations():
    """Pre-carga duraciones de todos los videos al inicio."""
    videos = get_videos_from_dir(VIDEOS_DIR)
    print(f"\n   Cargando duraciones de {len(videos)} videos...")
    for v in videos:
        get_cached_duration(v)
    print(f"   [OK] Duraciones cargadas.")


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def ask_visual_settings():
    """Pregunta las opciones visuales al inicio: fill mode y background."""
    print("\n   --- Opciones visuales ---")

    # Fill mode
    print("\n   Como mostrar los videos?")
    print("      1. cover  - Cubren todo (puede cortar bordes)")
    print("      2. fit    - Se ven completos (con fondo donde sobre)")
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
        print("      3. blur   - Mismo frame borroso de fondo")
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
    print("   GENERADOR VIDEO GENERICO - Drako Edits")
    print("=" * 50)

    audio_files = sorted(AUDIO_DIR.glob("*"))
    audio_files = [f for f in audio_files if f.suffix.lower() in {'.mp3', '.wav', '.ogg', '.m4a', '.aac'}]

    if not audio_files:
        print(f"\n   [X] No hay audios en {AUDIO_DIR}")
        sys.exit(1)

    print("\n   Audios disponibles:")
    for i, af in enumerate(audio_files, 1):
        dur = get_audio_duration(af)
        print(f"      {i}. {af.name} ({format_time(dur)})")

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


def show_eligible_videos(segment_duration):
    """Muestra videos que duran >= el segmento (se cortaran al final del tramo)."""
    all_videos = get_videos_from_dir(VIDEOS_DIR)
    eligible = []

    for v in all_videos:
        dur = get_cached_duration(v)
        if dur is not None and dur >= segment_duration:
            eligible.append((v, dur))

    if not eligible:
        print(f"\n   [!] No hay videos con duracion >= {format_time(segment_duration)}")
        print(f"   Videos disponibles (todos son mas cortos que el segmento):")
        for v in all_videos:
            dur = get_cached_duration(v)
            print(f"      - {v.name} ({format_time(dur) if dur else '???'})")
        return None

    print(f"\n   Videos elegibles (duracion >= {format_time(segment_duration)}):")
    for i, (v, dur) in enumerate(eligible, 1):
        gap = dur - segment_duration
        print(f"      {i}. {v.name} ({format_time(dur)}) [gap: {format_time(gap)}]")

    return eligible


def ask_video_start(video_path, segment_duration):
    """
    Pregunta desde que segundo empieza el video.
    Gap = duracion_video - duracion_segmento.
    Retorna el segundo de inicio (float).
    """
    vid_dur = get_cached_duration(video_path)
    gap = vid_dur - segment_duration

    if gap <= 0.01:
        # No hay gap, empieza desde 0 obligatoriamente
        print(f"   (Sin gap, empieza desde 0)")
        return 0.0

    print(f"   Gap disponible: {format_time(gap)} (puedes empezar desde 0 hasta {format_time(gap)})")
    while True:
        start_input = input(f"   Desde que segundo empieza el video? (Enter=0): ").strip()

        if not start_input:
            return 0.0

        try:
            start = float(start_input)
        except ValueError:
            print("   [!] Numero no valido.")
            continue

        if start < 0:
            print("   [!] No puede ser negativo.")
            continue

        if start > gap:
            print(f"   [!] Maximo es {format_time(gap)} (si no, el video no alcanza para el segmento).")
            continue

        print(f"   -> Empieza en: {format_time(start)}")
        return start


def ask_video(segment_duration, previous_video):
    """Pregunta el video para este segmento. Retorna (Path, raw_input_string, video_start)."""
    eligible = show_eligible_videos(segment_duration)

    if eligible is None:
        return None, None, 0.0

    prompt = "   Video"
    if previous_video:
        prompt += " ('misma' para repetir)"
    prompt += ": "

    while True:
        vid_input = input(prompt).strip()

        if not vid_input:
            print("   [!] Escribe algo.")
            continue

        if vid_input.lower() in ("misma", "mismo", "same") and previous_video:
            # Verificar que el video anterior todavia cabe (dura >= segmento)
            prev_dur = get_cached_duration(previous_video)
            if prev_dur and prev_dur >= segment_duration:
                print(f"   -> Usando mismo: {previous_video.name}")
                video_start = ask_video_start(previous_video, segment_duration)
                return previous_video, "same", video_start
            else:
                print(f"   [!] El video anterior ({previous_video.name}) es mas corto que este segmento.")
                continue

        # Buscar por numero
        if vid_input.isdigit():
            idx = int(vid_input) - 1
            if 0 <= idx < len(eligible):
                chosen = eligible[idx][0]
                print(f"   -> Video: {chosen.name}")
                video_start = ask_video_start(chosen, segment_duration)
                return chosen, chosen.name, video_start
            print("   [!] Numero fuera de rango.")
            continue

        # Buscar por nombre
        for v, dur in eligible:
            if v.stem.lower() == vid_input.lower() or v.name.lower() == vid_input.lower():
                print(f"   -> Video: {v.name}")
                video_start = ask_video_start(v, segment_duration)
                return v, v.name, video_start

        print(f"   [!] No se encontro '{vid_input}' entre los elegibles.")


def ask_subtitle(previous_subtitle):
    """Pregunta el subtitulo. Retorna (text_or_None, raw_input_string)."""
    prompt = "   Subtitulo (| = enter, ^ = subir, v = bajar)"
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


def ask_cuts(audio_duration):
    """Pregunta los cortes interactivamente."""
    segments = []
    previous_video = None
    previous_subtitle = None
    last_cut = 0.0
    json_segments = []

    print(f"\n   Duracion del audio: {audio_duration:.3f}s")
    print(f"   Define los cortes. En cada uno indicaras video y subtitulo.")
    print(f"   Opciones al pedir corte:")
    print(f"      - Un numero (ej. 4.59) = timestamp del corte")
    print(f"      - 'ultimo' = tramo final hasta el fin del audio")
    print(f"      - 'final' = cortar audio en el ultimo corte dado")
    print(f"   Para video/subtitulo: 'misma'/'mismo' repite el anterior.")
    print(f"   Solo se muestran videos cuya duracion >= la del segmento.")
    print(f"   El video se corta automaticamente al final del tramo.")
    print(f"   Puedes elegir desde que segundo empieza cada video (gap).")
    print(f"   En subtitulos: | = salto de linea, ^ = subir, v = bajar.")

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
            segment_duration = end_time - last_cut
            print(f"   Tramo: {last_cut:.3f}s -> {end_time:.3f}s (duracion: {format_time(segment_duration)})")

            vid_path, vid_input_raw, video_start = ask_video(segment_duration, previous_video)
            if vid_path is None:
                continue

            subtitle, sub_input_raw = ask_subtitle(previous_subtitle)

            segments.append({
                "start": last_cut,
                "end": end_time,
                "video_path": vid_path,
                "video_start": video_start,
                "subtitle": subtitle
            })
            json_segments.append({
                "end": "ultimo",
                "video": vid_input_raw,
                "video_start": video_start,
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

        segment_duration = cut_time - last_cut
        print(f"   Tramo: {last_cut:.3f}s -> {cut_time:.3f}s (duracion: {format_time(segment_duration)})")

        vid_path, vid_input_raw, video_start = ask_video(segment_duration, previous_video)
        if vid_path is None:
            continue

        subtitle, sub_input_raw = ask_subtitle(previous_subtitle)

        segments.append({
            "start": last_cut,
            "end": cut_time,
            "video_path": vid_path,
            "video_start": video_start,
            "subtitle": subtitle
        })
        json_segments.append({
            "end": cut_time,
            "video": vid_input_raw,
            "video_start": video_start,
            "subtitle": sub_input_raw
        })

        previous_video = vid_path
        previous_subtitle = subtitle
        last_cut = cut_time
        cut_num += 1

        print(f"   [OK] Tramo guardado. Siguiente...")


def ask_output_name():
    """Pregunta el nombre del archivo de salida."""
    name = input("\n   Nombre del video (sin .mp4): ").strip()
    if not name:
        name = "video_generic"
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
    output_name = config.get("output_name", "video_generic")
    fill_mode = config.get("fill_mode", "cover")
    background = config.get("background", "black")

    segments = []
    last_cut = 0.0

    for i, seg_config in enumerate(config["segments"]):
        end_raw = seg_config["end"]
        if end_raw == "ultimo":
            end_time = audio_duration
        else:
            end_time = float(end_raw)

        vid_raw = seg_config["video"]
        vid_path = VIDEOS_DIR / vid_raw
        if not vid_path.exists():
            print(f"   [X] Segmento {i+1}: video no encontrado '{vid_raw}'")
            sys.exit(1)

        video_start = float(seg_config.get("video_start", 0))

        sub_raw = seg_config.get("subtitle")
        if sub_raw and str(sub_raw).lower() == "same":
            # Buscar subtitle anterior
            subtitle = segments[-1]["subtitle"] if segments else None
        elif sub_raw is None or str(sub_raw).lower() in ("null", "none", "nada", "sin", ""):
            subtitle = None
        else:
            subtitle = str(sub_raw)

        segments.append({
            "start": last_cut,
            "end": end_time,
            "video_path": vid_path,
            "video_start": video_start,
            "subtitle": subtitle
        })

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
    print(f"   Reusar con: python generate_video_generic.py --json {config_path.name}")


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
    src_clips = []  # Guardar refs para cerrar al final

    for i, seg in enumerate(segments):
        start = seg["start"]
        end = min(seg["end"], total_duration)
        seg_duration = end - start
        if seg_duration <= 0:
            continue
        vid_path = seg["video_path"]
        video_start = seg.get("video_start", 0)
        subtitle = seg["subtitle"]

        print(f"   Segmento {i+1}: {start:.3f}s -> {end:.3f}s | video: {vid_path.name} [desde {format_time(video_start)}] | sub: {subtitle or '(sin)'}")

        # Cargar clip de video y recortar segun video_start + duracion del segmento
        src_clip = VideoFileClip(str(vid_path))
        src_clips.append(src_clip)  # No cerrar aqui, cerrar al final

        # Recortar: desde video_start hasta video_start + seg_duration
        clip_start = video_start
        clip_end = min(video_start + seg_duration, src_clip.duration - 0.01)
        src_clip = src_clip.subclipped(clip_start, clip_end)

        # Procesar frames segun fill_mode y background
        def make_frame_processor(fm, bg):
            def process_frame(frame):
                return process_video_frame(frame, fm, bg)
            return process_frame

        processed = src_clip.image_transform(make_frame_processor(fill_mode, background))
        processed = processed.with_start(start).with_duration(seg_duration)
        all_clips.append(processed)

        # Subtitle
        if subtitle:
            clean_text, y_offset = parse_subtitle_position(subtitle)
            if clean_text:
                sub_img = render_subtitle(clean_text, font_path)
                x_pos = max(0, (VIDEO_WIDTH - sub_img.shape[1]) // 2)
                y_pos = SUBTITLE_Y + y_offset
                sub_clip = (ImageClip(sub_img, transparent=True)
                            .with_position((x_pos, y_pos))
                            .with_start(start)
                            .with_duration(seg_duration))
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

    # Cerrar todo en orden correcto (final primero, luego sources)
    final.close()
    audio_clip.close()
    for sc in src_clips:
        try:
            sc.close()
        except (OSError, Exception):
            pass  # Ignorar WinError 6 en cleanup

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"\n   [OK] Listo: {output_path.name} ({size_mb:.1f} MB)")
    return output_path


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Drako Edits - Generador Video Generico",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python generate_video_generic.py                     # Interactivo
  python generate_video_generic.py --json config.json  # Config rapida
        """
    )
    parser.add_argument("--json", type=str, default=None,
                        help="Archivo JSON con la configuracion (rapido)")
    args = parser.parse_args()

    # Verificar carpetas
    if not AUDIO_DIR.exists():
        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        print(f"   [!] Se creo: {AUDIO_DIR}  <- coloca audios ahi")
    if not VIDEOS_DIR.exists():
        VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"   [!] Se creo: {VIDEOS_DIR}  <- coloca clips de video ahi")

    if not list(AUDIO_DIR.glob("*")):
        print(f"\n   [X] No hay audios en {AUDIO_DIR}")
        sys.exit(1)

    # --- MODO JSON (rapido) ---
    if args.json:
        print("\n>>> Drako Edits -- Generador Video Generico (Config Rapida)")
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

    # Pre-cargar duraciones de videos
    preload_durations()

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
        vs = seg.get('video_start', 0)
        vs_str = f" [desde {format_time(vs)}]" if vs > 0 else ""
        print(f"   {i}. [{seg['start']:.3f}s - {seg['end']:.3f}s] video: {seg['video_path'].name}{vs_str} | sub: {seg['subtitle'] or '(sin)'}")
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
