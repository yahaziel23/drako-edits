#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Paso 2: Descarga de Memes

Lee memes con status='por_descargar' de SQLite.
Para cada shortcode:
  1. Consulta tipo con instaloader (SIN login, 1 request a IG)
  2. Filtra por mínimo de likes
  3. Descarga según tipo:
     - GraphImage → foto directa con requests → status='listo_clasificar'
     - GraphVideo → descarga video, extrae frame con ffmpeg → status='pendiente_review'
     - GraphSidecar → skip (carousel) → status='rechazado'
  4. Branching: fotos van directo a IA, frames van a review manual

Protecciones:
  - Delay entre requests (configurable)
  - Pausa larga cada N posts
  - Límite máximo por sesión
  - Auto-stop en rate limit / login required
  - Skip de posts ya descargados (archivo existe)
  - Rate limiter budget (SQLite)

Uso:
    python 2_download_memes.py              # Descarga pendientes
    python 2_download_memes.py --max 10     # Solo 10
    python 2_download_memes.py --min-likes 10000
    python 2_download_memes.py --min-likes 0      # Sin filtro de likes
    python 2_download_memes.py --dry-run

Dependencias: instaloader, requests
"""

import sys
import os
import time
import random
import uuid
import hashlib
import argparse
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# Setup path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

import requests as req

try:
    import instaloader
except ImportError:
    print("   [X] pip install instaloader")
    sys.exit(1)

# Silenciar loggers de instaloader
logging.getLogger('instaloader').setLevel(logging.CRITICAL)
logging.getLogger('instaloader.instaloadercontext').setLevel(logging.CRITICAL)

from utils.db import init_db, get_db, get_memes_by_status, update_meme_status, start_pipeline_run, finish_pipeline_run
from utils.config import load_config, get_section
from utils.logger import setup_logger, get_logger, track_item, track_api_call, log_summary
from utils.health import run_health_checks
from utils.rate_limiter import RateLimiter
from utils.retry import retry_instagram
from utils.telegram import notify_error


# =============================================================================
# CONFIGURACION
# =============================================================================

MEMES_DIR = SCRIPT_DIR / "memes_descargados"
TEMP_DIR = SCRIPT_DIR / "_temp_video"


# =============================================================================
# INSTALOADER HELPERS
# =============================================================================

def create_instaloader():
    """Crea instancia de instaloader SIN LOGIN (solo queries)."""
    L = instaloader.Instaloader(
        download_videos=False,
        download_video_thumbnails=False,
        download_comments=False,
        download_geotags=False,
        save_metadata=False,
        quiet=True,
    )
    return L


def silent_query(L_context, shortcode):
    """
    Ejecuta Post.from_shortcode() suprimiendo stderr.
    Instaloader imprime '403 Forbidden [retrying]' directo a stderr.
    """
    old_stderr = sys.stderr
    try:
        sys.stderr = open(os.devnull, 'w')
        post = instaloader.Post.from_shortcode(L_context, shortcode)
    finally:
        sys.stderr.close()
        sys.stderr = old_stderr
    return post


# =============================================================================
# DESCARGA
# =============================================================================

def download_file(url, output_path):
    """
    Descarga un archivo de una URL con requests.
    Returns: True si exitoso (archivo >1KB).
    """
    try:
        response = req.get(url, stream=True, timeout=60)
        response.raise_for_status()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path.exists() and output_path.stat().st_size > 1000
    except Exception as e:
        get_logger().error(f"Error descargando {url[:60]}: {e}")
        return False


def extract_first_frame(video_path, output_path):
    """
    Extrae el primer frame de un video usando ffmpeg.
    Returns: True si exitoso.
    """
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 1000
    except Exception:
        return False


def compute_file_hash(filepath):
    """Calcula SHA-256 de un archivo (para cache/dedup)."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================
# PROCESAMIENTO PRINCIPAL
# =============================================================================

def process_shortcode(L, shortcode, min_likes, is_dry_run):
    """
    Procesa un shortcode:
    1. Query a IG (tipo + métricas)
    2. Filtro de likes
    3. Descarga según tipo
    4. Actualiza SQLite con branching
    
    Returns: 'foto' | 'frame' | 'skip_carousel' | 'skip_low_likes' | 'error' | 'rate_limit'
    """
    log = get_logger()
    
    # Verificar si ya tiene archivo descargado
    image_path = MEMES_DIR / f"{shortcode}.jpg"
    if image_path.exists() and not is_dry_run:
        # Ya descargado, solo actualizar status
        file_hash = compute_file_hash(image_path)
        update_meme_status(shortcode, 'listo_clasificar',
                          image_path=str(image_path),
                          image_hash=file_hash,
                          downloaded_at=datetime.now().isoformat())
        log.info(f"  {shortcode} -> ya existía, status actualizado")
        return 'foto'  # Asumimos foto si ya existe
    
    # === QUERY A IG ===
    try:
        post = silent_query(L.context, shortcode)
    except instaloader.exceptions.QueryReturnedNotFoundException:
        log.warning(f"  {shortcode} -> no encontrado (borrado?)")
        if not is_dry_run:
            update_meme_status(shortcode, 'rechazado')
        return 'error'
    except instaloader.exceptions.ConnectionException as e:
        error_str = str(e).lower()
        if any(x in error_str for x in ['429', 'rate', 'login', 'redirect', '403']):
            log.error(f"  {shortcode} -> RATE LIMIT / BLOCKED")
            return 'rate_limit'
        log.error(f"  {shortcode} -> conexión: {e}")
        return 'error'
    except Exception as e:
        log.error(f"  {shortcode} -> error: {e}")
        return 'error'
    
    track_api_call()
    
    # === MÉTRICAS ===
    typename = post.typename
    likes = post.likes or 0
    comments = post.comments or 0
    views = getattr(post, 'video_view_count', None) if typename == 'GraphVideo' else None
    
    # === FILTRO DE LIKES ===
    if likes < min_likes:
        log.info(f"  {shortcode} -> {likes} likes (min: {min_likes}). Skip.")
        if not is_dry_run:
            update_meme_status(shortcode, 'rechazado',
                              likes=likes, comments=comments,
                              source_type=typename.lower().replace('graph', ''))
        return 'skip_low_likes'
    
    # === CAROUSEL -> SKIP ===
    if typename == 'GraphSidecar':
        log.info(f"  {shortcode} -> Carousel. Skip.")
        if not is_dry_run:
            update_meme_status(shortcode, 'rechazado',
                              likes=likes, comments=comments,
                              source_type='carousel')
        return 'skip_carousel'
    
    if is_dry_run:
        log.info(f"  [DRY] {shortcode} -> {typename}, {likes} likes")
        return 'foto' if typename == 'GraphImage' else 'frame'
    
    # === GRAPHIMAGE -> DESCARGA FOTO ===
    if typename == 'GraphImage':
        url = post.url
        MEMES_DIR.mkdir(parents=True, exist_ok=True)
        
        success = download_file(url, image_path)
        if success:
            file_hash = compute_file_hash(image_path)
            size_kb = image_path.stat().st_size / 1024
            update_meme_status(shortcode, 'listo_clasificar',
                              source_type='foto',
                              likes=likes, comments=comments,
                              image_path=str(image_path),
                              image_hash=file_hash,
                              downloaded_at=datetime.now().isoformat())
            log.info(f"  {shortcode} -> FOTO ({size_kb:.0f}KB, {likes} likes) → listo_clasificar")
            return 'foto'
        else:
            log.error(f"  {shortcode} -> Error descargando foto")
            return 'error'
    
    # === GRAPHVIDEO -> EXTRAER FRAME ===
    if typename == 'GraphVideo':
        video_url = post.video_url
        MEMES_DIR.mkdir(parents=True, exist_ok=True)
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        
        # Descargar video a temp
        temp_video = TEMP_DIR / f"{shortcode}.mp4"
        success = download_file(video_url, temp_video)
        
        if not success:
            log.error(f"  {shortcode} -> Error descargando video")
            return 'error'
        
        # Extraer primer frame
        success = extract_first_frame(temp_video, image_path)
        
        # Borrar video temporal
        if temp_video.exists():
            temp_video.unlink()
        
        if success:
            file_hash = compute_file_hash(image_path)
            size_kb = image_path.stat().st_size / 1024
            update_meme_status(shortcode, 'pendiente_review',
                              source_type='frame',
                              likes=likes, comments=comments,
                              views=views,
                              image_path=str(image_path),
                              image_hash=file_hash,
                              downloaded_at=datetime.now().isoformat())
            log.info(f"  {shortcode} -> FRAME ({size_kb:.0f}KB, {likes} likes) → pendiente_review")
            return 'frame'
        else:
            log.error(f"  {shortcode} -> Error extrayendo frame")
            return 'error'
    
    # Tipo desconocido
    log.warning(f"  {shortcode} -> tipo desconocido: {typename}")
    return 'error'


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Paso 2: Descarga de memes")
    parser.add_argument('--max', type=int, default=None,
                        help="Máximo de posts a procesar (default: config)")
    parser.add_argument('--min-likes', type=int, default=None,
                        help="Mínimo de likes (default: config)")
    parser.add_argument('--dry-run', action='store_true',
                        help="No descarga ni modifica DB")
    args = parser.parse_args()

    # Setup
    setup_logger('2_download_memes')
    log = get_logger()
    config = load_config()
    dl_cfg = get_section('descarga')

    # Health checks
    run_health_checks(checks=['config', 'db', 'dirs', 'cleanup'])

    # Parámetros
    max_por_sesion = args.max or dl_cfg.get('max_por_sesion', 50)
    min_likes = args.min_likes if args.min_likes is not None else dl_cfg.get('min_likes', 5000)
    delay_entre_posts = dl_cfg.get('delay_entre_posts', 5)
    pausa_cada_n = dl_cfg.get('pausa_cada_n', 20)
    pausa_duracion = dl_cfg.get('pausa_duracion_s', 180)
    is_dry_run = args.dry_run or config.get('dry_run', False)

    log.info(f"Max por sesión: {max_por_sesion}")
    log.info(f"Min likes: {min_likes}")
    log.info(f"Delay: {delay_entre_posts}s entre posts")
    log.info(f"Dry run: {is_dry_run}")

    # Rate limiter
    limiter = RateLimiter('instagram')
    if not limiter.can_request():
        log.error("Budget de Instagram agotado. Abortando.")
        sys.exit(1)

    # Inicializar DB y obtener pendientes
    init_db()
    pending = get_memes_by_status('por_descargar', limit=max_por_sesion)

    if not pending:
        log.info("No hay memes por descargar. Todo al día.")
        return

    log.info(f"Pendientes de descarga: {len(pending)}")

    # Pipeline run tracking
    run_id = uuid.uuid4().hex[:12]
    start_pipeline_run(run_id, '2_download_memes')
    start_time = time.time()

    # Crear instaloader
    L = create_instaloader()

    # Stats
    stats = {'foto': 0, 'frame': 0, 'skip_carousel': 0,
             'skip_low_likes': 0, 'error': 0, 'rate_limit': False}

    # Procesar
    for i, meme in enumerate(pending, 1):
        shortcode = meme['shortcode']
        log.info(f"[{i}/{len(pending)}] {shortcode}")

        # Rate limit check
        if not limiter.can_request():
            log.warning("Budget de IG alcanzado. Deteniendo.")
            break

        # Procesar
        result = process_shortcode(L, shortcode, min_likes, is_dry_run)

        if result == 'rate_limit':
            stats['rate_limit'] = True
            log.error("RATE LIMIT detectado. Deteniendo para evitar ban.")
            notify_error('2_download', 'Rate limit de Instagram detectado')
            break
        
        stats[result] = stats.get(result, 0) + 1
        limiter.log_request()

        if result in ('foto', 'frame'):
            track_item('processed')
        elif result in ('skip_carousel', 'skip_low_likes'):
            track_item('skipped')
        else:
            track_item('error')

        # Delay entre posts
        if i < len(pending):
            jitter = random.uniform(0.5, 2.0)
            time.sleep(delay_entre_posts + jitter)

        # Pausa larga cada N posts
        if i > 0 and i % pausa_cada_n == 0 and i < len(pending):
            log.info(f"  --- Pausa de {pausa_duracion}s (cada {pausa_cada_n} posts) ---")
            time.sleep(pausa_duracion)

    # Cleanup temp
    if TEMP_DIR.exists():
        import shutil
        shutil.rmtree(TEMP_DIR, ignore_errors=True)

    # Registrar fin
    duration = time.time() - start_time
    total_processed = stats['foto'] + stats['frame']
    total_skipped = stats['skip_carousel'] + stats['skip_low_likes']
    finish_pipeline_run(
        run_id, '2_download_memes',
        status='success' if not stats['rate_limit'] else 'error',
        items_processed=total_processed,
        items_skipped=total_skipped,
        items_error=stats['error'],
        duration_s=round(duration, 2)
    )

    # Resumen
    log.info("")
    log.info("=" * 60)
    log.info("   RESUMEN - DESCARGA DE MEMES")
    log.info("=" * 60)
    log.info(f"   Fotos descargadas:       {stats['foto']} → listo_clasificar")
    log.info(f"   Frames extraídos:         {stats['frame']} → pendiente_review")
    log.info(f"   Skip (carousel):         {stats['skip_carousel']}")
    log.info(f"   Skip (low likes):        {stats['skip_low_likes']}")
    log.info(f"   Errores:                 {stats['error']}")
    log.info(f"   Rate limited:            {stats['rate_limit']}")
    log.info(f"   Duración:                {duration:.1f}s")
    if is_dry_run:
        log.info(f"   [DRY RUN - nada descargado]")
    log.info("=" * 60)

    log_summary()


if __name__ == "__main__":
    main()
