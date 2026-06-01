#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Preprocess Clips

Detecta y recorta bordes negros (letterbox/pillarbox) de los clips de reaccion.
Usa ffmpeg cropdetect para encontrar el area real de contenido y recorta.

Flujo:
  1. Lee clips de la carpeta clips/
  2. Para cada clip: detecta bordes negros con cropdetect
  3. Si tiene bordes: recorta y reemplaza el archivo original
  4. Guarda backup en clips/originals/ por si se necesita re-procesar
  5. Actualiza dimensiones en SQLite

Uso:
    python preprocess_clips.py                # Procesa clips sin preprocesar
    python preprocess_clips.py --all          # Re-procesa todos (incluso ya procesados)
    python preprocess_clips.py --clip clip_id # Solo un clip especifico
    python preprocess_clips.py --preview      # Solo muestra que recortaria, sin aplicar
"""

import sys
import os
import re
import subprocess
import shutil
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db
from utils.logger import setup_logger, get_logger

CLIPS_DIR = SCRIPT_DIR / "clips"
ORIGINALS_DIR = CLIPS_DIR / "originals"

# Minimum crop: if detected crop removes less than this many px total, skip
MIN_CROP_PIXELS = 20


def get_video_dimensions(video_path):
    """Obtiene width x height del video."""
    cmd = [
        'ffprobe', '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height',
        '-of', 'csv=p=0:s=x',
        str(video_path)
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            parts = result.stdout.strip().split('x')
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None, None


def detect_crop(video_path, sample_duration=5):
    """
    Usa ffmpeg cropdetect para encontrar el area real de contenido.
    Analiza N segundos del video y toma el crop mas comun.
    
    Returns: (w, h, x, y) o None si no hay crop necesario.
    """
    log = get_logger()
    
    # Get video duration
    duration_cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0',
        str(video_path)
    ]
    try:
        dur_result = subprocess.run(duration_cmd, capture_output=True, text=True, timeout=10)
        total_duration = float(dur_result.stdout.strip())
    except Exception:
        total_duration = 10.0
    
    # Sample from middle of video (avoids black intro/outro)
    start_time = max(0, (total_duration - sample_duration) / 2)
    
    # Run cropdetect
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_time),
        '-i', str(video_path),
        '-t', str(min(sample_duration, total_duration)),
        '-vf', 'cropdetect=24:2:0',  # threshold=24, round=2, skip=0
        '-f', 'null', '-'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        stderr = result.stderr
    except Exception as e:
        log.warning(f"    cropdetect fallo: {e}")
        return None
    
    # Parse crop values from stderr
    # Format: [Parsed_cropdetect_0 ...] crop=W:H:X:Y
    crops = re.findall(r'crop=(\d+):(\d+):(\d+):(\d+)', stderr)
    
    if not crops:
        return None
    
    # Take the most common crop value (mode)
    from collections import Counter
    crop_counts = Counter(crops)
    best_crop = crop_counts.most_common(1)[0][0]
    
    w, h, x, y = int(best_crop[0]), int(best_crop[1]), int(best_crop[2]), int(best_crop[3])
    
    # Get original dimensions
    orig_w, orig_h = get_video_dimensions(video_path)
    if orig_w is None:
        return None
    
    # Check if crop is significant
    removed_px = (orig_w - w) + (orig_h - h)
    if removed_px < MIN_CROP_PIXELS:
        return None  # No significant crop needed
    
    return (w, h, x, y)


def apply_crop(video_path, crop_params, output_path):
    """
    Aplica el crop al video con ffmpeg.
    crop_params: (w, h, x, y)
    """
    w, h, x, y = crop_params
    crop_filter = f"crop={w}:{h}:{x}:{y}"
    
    cmd = [
        'ffmpeg', '-y',
        '-i', str(video_path),
        '-vf', crop_filter,
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '18',  # High quality for clips (they're short)
        '-c:a', 'copy',
        '-pix_fmt', 'yuv420p',
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except Exception:
        return False


def process_clip(clip_id, clip_path, preview_only=False):
    """
    Procesa un clip: detecta crop y aplica.
    Returns: dict con resultado o None si no necesita crop.
    """
    log = get_logger()
    
    if not clip_path.exists():
        log.warning(f"    Archivo no encontrado: {clip_path.name}")
        return None
    
    orig_w, orig_h = get_video_dimensions(clip_path)
    if orig_w is None:
        log.warning(f"    No se pudo leer dimensiones: {clip_path.name}")
        return None
    
    # Detect crop
    crop = detect_crop(clip_path)
    
    if crop is None:
        log.info(f"    Sin bordes negros ({orig_w}x{orig_h})")
        return {'action': 'skip', 'reason': 'no_crop_needed'}
    
    w, h, x, y = crop
    removed_w = orig_w - w
    removed_h = orig_h - h
    
    log.info(f"    Original: {orig_w}x{orig_h}")
    log.info(f"    Crop:     {w}x{h} (quitar {removed_w}px ancho, {removed_h}px alto)")
    log.info(f"    Offset:   x={x}, y={y}")
    
    if preview_only:
        return {'action': 'preview', 'original': f"{orig_w}x{orig_h}", 'crop': f"{w}x{h}", 'removed': f"-{removed_w}w -{removed_h}h"}
    
    # Backup original
    ORIGINALS_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = ORIGINALS_DIR / clip_path.name
    if not backup_path.exists():
        shutil.copy2(clip_path, backup_path)
    
    # Apply crop to temp file, then replace original
    temp_output = clip_path.with_suffix('.crop.mp4')
    
    success = apply_crop(clip_path, crop, temp_output)
    
    if success and temp_output.exists() and temp_output.stat().st_size > 1000:
        # Replace original with cropped version
        clip_path.unlink()
        temp_output.rename(clip_path)
        
        # Update DB
        db = get_db()
        db.execute("""
            UPDATE clips SET preprocessed = 1, crop_applied = ?
            WHERE id = ?
        """, (f"{w}:{h}:{x}:{y}", clip_id))
        db.commit()
        
        new_size = clip_path.stat().st_size / 1024
        log.info(f"    OK: {clip_path.name} ({new_size:.0f}KB)")
        return {'action': 'cropped', 'from': f"{orig_w}x{orig_h}", 'to': f"{w}x{h}"}
    else:
        # Cleanup failed attempt
        if temp_output.exists():
            temp_output.unlink()
        log.error(f"    Error aplicando crop")
        return {'action': 'error'}


def ensure_db_columns():
    """Agrega columnas de preprocess a clips si no existen."""
    db = get_db()
    new_cols = [
        ("preprocessed", "INTEGER DEFAULT 0"),
        ("crop_applied", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        try:
            db.execute(f"ALTER TABLE clips ADD COLUMN {col_name} {col_type}")
            db.commit()
        except Exception:
            pass  # Column already exists


def main():
    parser = argparse.ArgumentParser(description="Preprocess Clips - Auto-crop black bars")
    parser.add_argument('--all', action='store_true', help="Re-procesar todos los clips")
    parser.add_argument('--clip', type=str, default=None, help="Solo un clip por ID")
    parser.add_argument('--preview', action='store_true', help="Solo mostrar que recortaria")
    args = parser.parse_args()
    
    init_db()
    setup_logger('preprocess_clips')
    log = get_logger()
    ensure_db_columns()
    
    log.info("")
    log.info("=======================================================")
    log.info("   PREPROCESS CLIPS - Auto-crop bordes negros")
    log.info("=======================================================")
    
    db = get_db()
    
    # Get clips to process
    if args.clip:
        rows = db.execute("SELECT id, filename FROM clips WHERE id = ?", (args.clip,)).fetchall()
    elif args.all:
        rows = db.execute("SELECT id, filename FROM clips WHERE approved = 1").fetchall()
    else:
        # Only unprocessed clips
        rows = db.execute("SELECT id, filename FROM clips WHERE approved = 1 AND (preprocessed = 0 OR preprocessed IS NULL)").fetchall()
    
    if not rows:
        log.info("   No hay clips para procesar.")
        return
    
    log.info(f"   Clips a procesar: {len(rows)}")
    if args.preview:
        log.info("   MODO PREVIEW (no aplica cambios)")
    log.info("")
    
    cropped = 0
    skipped = 0
    errors = 0
    
    for i, row in enumerate(rows):
        clip_id = row['id']
        filename = row['filename']
        clip_path = CLIPS_DIR / filename
        
        log.info(f"  [{i+1}/{len(rows)}] {clip_id}")
        
        result = process_clip(clip_id, clip_path, preview_only=args.preview)
        
        if result is None or result['action'] == 'error':
            errors += 1
        elif result['action'] == 'skip':
            skipped += 1
            # Mark as preprocessed (no crop needed)
            if not args.preview:
                db.execute("UPDATE clips SET preprocessed = 1 WHERE id = ?", (clip_id,))
                db.commit()
        elif result['action'] in ('cropped', 'preview'):
            cropped += 1
    
    log.info("")
    log.info("=======================================================")
    log.info("   RESUMEN")
    log.info("=======================================================")
    log.info(f"   Recortados:  {cropped}")
    log.info(f"   Sin cambio:  {skipped}")
    log.info(f"   Errores:     {errors}")
    log.info("=======================================================")
    
    if cropped > 0 and not args.preview:
        log.info("")
        log.info("   Backups en: clips/originals/")
        log.info("   Si algun crop salio mal:")
        log.info("     python preprocess_clips.py --clip CLIP_ID --all")
        log.info("   O usa REDESCARGAR en catalogo_clips.py")


if __name__ == '__main__':
    main()
