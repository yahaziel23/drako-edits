#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Generar Video

Ensambla el video final vertical (1080x1920):
  - Meme (imagen, top ~65%)
  - Caption (texto overlay estilo TikTok)
  - Clip de reaccion (video, bottom ~30%)
  - Audio del clip original

Lee matches confirmados de SQLite y genera los .mp4 finales.

Requisitos:
    ffmpeg en PATH
    Pillow (para generar caption overlay)

Uso:
    python 7_generate_video.py                    # Genera todos los pendientes
    python 7_generate_video.py --shortcode ABC    # Solo un meme
    python 7_generate_video.py --dry-run          # Preview sin generar
    python 7_generate_video.py --force            # Re-genera incluso ya generados
    python 7_generate_video.py --caption-size L   # Override tamano de caption

Output: videos/{shortcode}_v{n}.mp4
"""

import sys
import os
import json
import argparse
import subprocess
import uuid
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db
from utils.config import load_config, get_config
from utils.logger import setup_logger, get_logger

# Directorios
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
CLIPS_DIR = SCRIPT_DIR / "clips"
VIDEOS_DIR = SCRIPT_DIR / "videos"
TEMP_DIR = SCRIPT_DIR / "_temp_gen"

# Dimensiones del video final
WIDTH = 1080
HEIGHT = 1920
FPS = 30

# Proporciones
MEME_RATIO = 0.65      # Meme ocupa 65% superior
CLIP_RATIO = 0.30      # Clip ocupa 30% inferior
GAP_RATIO = 0.05       # 5% gap para caption

# Caption config
CAPTION_SIZES = {'S': 42, 'M': 58, 'L': 76, 'XL': 100}
CAPTION_FONT = 'Arial'  # Fallback, ffmpeg usa fontfile si existe
STROKE_WIDTH = 3


def ensure_dirs():
    VIDEOS_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)


def get_pending_videos(force=False, shortcode=None):
    """Obtiene memes listos para generar video."""
    db = get_db()
    
    if shortcode:
        rows = db.execute("""
            SELECT m.shortcode, m.image_path, m.status,
                   mt.clip_id, mt.caption, mt.caption_size, mt.accuracy, mt.id as match_id,
                   cl.filename as clip_filename, cl.duracion_s as clip_duration
            FROM memes m
            JOIN matches mt ON m.shortcode = mt.shortcode AND mt.match_type = 'confirmed'
            JOIN clips cl ON mt.clip_id = cl.id
            WHERE m.shortcode = ?
        """, (shortcode,)).fetchall()
    elif force:
        rows = db.execute("""
            SELECT m.shortcode, m.image_path, m.status,
                   mt.clip_id, mt.caption, mt.caption_size, mt.accuracy, mt.id as match_id,
                   cl.filename as clip_filename, cl.duracion_s as clip_duration
            FROM memes m
            JOIN matches mt ON m.shortcode = mt.shortcode AND mt.match_type = 'confirmed'
            JOIN clips cl ON mt.clip_id = cl.id
            WHERE m.status IN ('por_generar', 'generado')
        """).fetchall()
    else:
        rows = db.execute("""
            SELECT m.shortcode, m.image_path, m.status,
                   mt.clip_id, mt.caption, mt.caption_size, mt.accuracy, mt.id as match_id,
                   cl.filename as clip_filename, cl.duracion_s as clip_duration
            FROM memes m
            JOIN matches mt ON m.shortcode = mt.shortcode AND mt.match_type = 'confirmed'
            JOIN clips cl ON mt.clip_id = cl.id
            WHERE m.status = 'por_generar'
        """).fetchall()
    
    return rows


def find_meme_image(shortcode):
    """Encuentra la imagen del meme."""
    for ext in ['.jpg', '.png', '.webp']:
        path = MEMES_DIR / (shortcode + ext)
        if path.exists():
            return path
    return None


def get_image_dimensions(image_path):
    """Obtiene dimensiones de una imagen con ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-print_format', 'json',
        '-show_streams',
        str(image_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        data = json.loads(result.stdout)
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                return int(stream['width']), int(stream['height'])
    return None, None


def get_video_duration(video_path):
    """Obtiene duracion de un video."""
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        str(video_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return 5.0  # default


def generate_video(shortcode, meme_image, clip_path, caption, caption_size='M', match_id=None):
    """
    Genera el video final con ffmpeg.
    
    Layout (1080x1920):
    ┌─────────────────┐
    │                 │
    │   MEME IMAGE    │  ~65% = 1248px
    │                 │
    ├─────────────────┤
    │  CAPTION TEXT   │  ~5% = 96px (gap/overlay area)
    ├─────────────────┤
    │   CLIP VIDEO    │  ~30% = 576px
    └─────────────────┘
    """
    log = get_logger()
    
    # Calculate zones
    meme_h = int(HEIGHT * MEME_RATIO)    # 1248
    clip_h = int(HEIGHT * CLIP_RATIO)    # 576
    clip_y = HEIGHT - clip_h              # 1344
    
    # Video duration = clip duration
    duration = get_video_duration(clip_path)
    
    # Determine variant number
    db = get_db()
    existing = db.execute(
        "SELECT COUNT(*) as cnt FROM videos_generados WHERE shortcode = ?",
        (shortcode,)
    ).fetchone()['cnt']
    variant = existing + 1
    
    # Output path
    output_filename = f"{shortcode}_v{variant}.mp4"
    output_path = VIDEOS_DIR / output_filename
    
    # Build ffmpeg command
    # Strategy:
    # 1. Black background 1080x1920 for duration of clip
    # 2. Scale meme to fit 1080 wide, max meme_h tall, pad with black
    # 3. Scale clip to 1080 wide, clip_h tall
    # 4. Overlay meme at top, clip at bottom
    # 5. Draw caption text in the gap area
    
    font_size = CAPTION_SIZES.get(caption_size, CAPTION_SIZES['M'])
    
    # Escape caption for ffmpeg drawtext
    caption_escaped = ''
    if caption:
        # ffmpeg drawtext escaping: replace special chars
        caption_escaped = caption.replace("'", "\u2019")  # curly quote
        caption_escaped = caption_escaped.replace(':', '\\:')
        caption_escaped = caption_escaped.replace('%', '%%')
    
    # Build filter_complex
    filters = []
    
    # Input 0: black background
    # Input 1: meme image
    # Input 2: clip video
    
    # Scale meme: fit within 1080 x meme_h, center vertically
    filters.append(f'[1:v]scale={WIDTH}:{meme_h}:force_original_aspect_ratio=decrease,pad={WIDTH}:{meme_h}:(ow-iw)/2:(oh-ih)/2:black[meme]')
    
    # Scale clip: fit within 1080 x clip_h, center
    filters.append(f'[2:v]scale={WIDTH}:{clip_h}:force_original_aspect_ratio=decrease,pad={WIDTH}:{clip_h}:(ow-iw)/2:(oh-ih)/2:black[clip]')
    
    # Create black background with duration
    filters.append(f'color=black:s={WIDTH}x{HEIGHT}:d={duration}:r={FPS}[bg]')
    
    # Overlay meme on top
    filters.append('[bg][meme]overlay=0:0:shortest=1[v1]')
    
    # Overlay clip at bottom
    filters.append(f'[v1][clip]overlay=0:{clip_y}:shortest=1[v2]')
    
    # Add caption text if provided
    if caption_escaped:
        # Caption position: centered, in the gap between meme and clip
        caption_y = meme_h - int(font_size * 0.8)  # slightly above the gap
        
        # White text with black outline (TikTok style)
        drawtext = (
            f"drawtext=text='{caption_escaped}'"
            f":fontsize={font_size}"
            f":fontcolor=white"
            f":borderw={STROKE_WIDTH}"
            f":bordercolor=black"
            f":x=(w-text_w)/2"
            f":y={caption_y}"
            f":font='{CAPTION_FONT}'"
        )
        filters.append(f'[v2]{drawtext}[vout]')
        final_video = '[vout]'
    else:
        final_video = '[v2]'
    
    filter_complex = ';'.join(filters)
    
    # Build ffmpeg command
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-i', str(meme_image),       # Input 1: meme image (looped)
        '-i', str(clip_path),                       # Input 2: clip video
        '-filter_complex', filter_complex,
        '-map', final_video,                         # Video output
        '-map', '1:a?',                              # Audio from clip (if exists)
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-t', str(duration),
        '-pix_fmt', 'yuv420p',
        '-r', str(FPS),
        str(output_path)
    ]
    
    log.info(f"    Generando video ({duration:.1f}s)...")
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    
    if result.returncode != 0:
        log.error(f"    ffmpeg error: {result.stderr[-300:]}")
        return None
    
    if not output_path.exists() or output_path.stat().st_size < 10000:
        log.error(f"    Video generado invalido o muy pequeno")
        return None
    
    # Register in DB
    size_mb = output_path.stat().st_size / (1024 * 1024)
    config_json = json.dumps({
        'caption': caption,
        'caption_size': caption_size,
        'font_size': font_size,
        'meme_ratio': MEME_RATIO,
        'clip_ratio': CLIP_RATIO,
        'duration_s': duration,
    }, ensure_ascii=False)
    
    db.execute("""
        INSERT INTO videos_generados (shortcode, match_id, output_path, config_json, 
                                      duracion_s, width, height, variante_num)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        shortcode, match_id, str(output_path), config_json,
        duration, WIDTH, HEIGHT, variant
    ))
    
    # Update meme status
    db.execute("UPDATE memes SET status = 'generado' WHERE shortcode = ?", (shortcode,))
    db.commit()
    
    log.info(f"    OK: {output_filename} ({size_mb:.1f}MB, {duration:.1f}s)")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Generar videos meme + clip")
    parser.add_argument('--force', action='store_true', help="Re-genera todos")
    parser.add_argument('--shortcode', type=str, default=None, help="Solo un meme")
    parser.add_argument('--dry-run', action='store_true', help="Preview sin generar")
    parser.add_argument('--caption-size', type=str, default=None, 
                        choices=['S', 'M', 'L', 'XL'], help="Override caption size")
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('generate_video')
    log = get_logger()
    ensure_dirs()
    
    # Verify ffmpeg
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=5)
    except Exception:
        log.error("ffmpeg no encontrado. Instalalo y asegurate que esta en PATH.")
        sys.exit(1)
    
    # Get pending
    pending = get_pending_videos(force=args.force, shortcode=args.shortcode)
    
    if not pending:
        log.info("No hay videos pendientes de generar.")
        log.info("Confirma matches primero: python catalogo_matches.py --apply")
        return
    
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   GENERAR VIDEOS")
    log.info(f"{'='*55}")
    log.info(f"   Pendientes: {len(pending)}")
    log.info(f"   Output: {VIDEOS_DIR}/")
    log.info(f"   Formato: {WIDTH}x{HEIGHT} @ {FPS}fps")
    log.info(f"{'='*55}")
    log.info(f"")
    
    if args.dry_run:
        log.info("[DRY RUN] Videos que se generarian:")
        for row in pending:
            cap = f'"{row["caption"]}"' if row['caption'] else '(sin caption)'
            log.info(f"  {row['shortcode']} + {row['clip_filename']} | {cap}")
        return
    
    generated = 0
    errors = 0
    
    for i, row in enumerate(pending):
        shortcode = row['shortcode']
        clip_filename = row['clip_filename']
        caption = row['caption'] or ''
        caption_size = args.caption_size or row['caption_size'] or 'M'
        match_id = row['match_id']
        
        log.info(f"  [{i+1}/{len(pending)}] {shortcode}")
        log.info(f"    Clip: {clip_filename}")
        log.info(f"    Caption: {caption if caption else '(sin caption)'}")
        log.info(f"    Size: {caption_size} ({CAPTION_SIZES.get(caption_size, '?')}px)")
        
        # Find files
        meme_image = find_meme_image(shortcode)
        clip_path = CLIPS_DIR / clip_filename
        
        if not meme_image:
            log.error(f"    Imagen del meme no encontrada")
            errors += 1
            continue
        
        if not clip_path.exists():
            log.error(f"    Clip no encontrado: {clip_filename}")
            errors += 1
            continue
        
        # Generate
        result = generate_video(
            shortcode=shortcode,
            meme_image=meme_image,
            clip_path=clip_path,
            caption=caption,
            caption_size=caption_size,
            match_id=match_id
        )
        
        if result:
            generated += 1
        else:
            errors += 1
    
    # Summary
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   RESUMEN GENERACION")
    log.info(f"{'='*55}")
    log.info(f"   Generados: {generated}")
    log.info(f"   Errores:   {errors}")
    log.info(f"{'='*55}")
    log.info(f"")
    
    if generated > 0:
        log.info(f"   Siguiente paso:")
        log.info(f"     python preview_videos.py")
        log.info(f"     (revisar videos antes de subir)")


if __name__ == "__main__":
    main()
