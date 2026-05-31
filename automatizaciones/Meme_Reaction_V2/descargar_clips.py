#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Descargar Clips de Reaccion

Descarga clips de YouTube con yt-dlp, los trimea al rango deseado,
extrae audio por separado, y los registra en SQLite.

Requisitos:
    pip install yt-dlp
    ffmpeg instalado y en PATH

Uso:
    # Descargar clip completo
    python descargar_clips.py "https://youtube.com/watch?v=XXX"

    # Descargar con trim (segundos)
    python descargar_clips.py "https://youtube.com/watch?v=XXX" --start 5 --end 12

    # Descargar con trim (formato mm:ss)
    python descargar_clips.py "https://youtube.com/watch?v=XXX" --start 1:05 --end 1:12

    # Descargar solo audio de un video (para usar como musica en otro clip)
    python descargar_clips.py "https://youtube.com/watch?v=XXX" --solo-audio

    # Batch: descargar multiples de un archivo .txt
    python descargar_clips.py --batch clips_pendientes.txt

Formato del archivo batch (.txt):
    # Comentarios con #
    https://youtube.com/watch?v=XXX 5 12
    https://youtube.com/watch?v=YYY 0 8
    https://youtube.com/watch?v=ZZZ  (sin trim = completo)

Notas:
    - Los clips se guardan en formato HORIZONTAL (landscape)
    - Se escalan a max 1080px de ancho manteniendo aspect ratio
    - El audio se extrae por separado a audio/ (para reusar)
    - Todo se registra en SQLite (tabla clips)
"""

import sys
import os
import argparse
import subprocess
import uuid
import json
import re
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db
from utils.config import load_config
from utils.logger import setup_logger, get_logger

# Directorios
CLIPS_DIR = SCRIPT_DIR / "clips"
AUDIO_DIR = SCRIPT_DIR / "audio"
TEMP_DIR = SCRIPT_DIR / "temp_clips"


def ensure_dirs():
    """Crea directorios necesarios."""
    CLIPS_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)


def parse_time(time_str):
    """Convierte tiempo en formato flexible a segundos.
    Acepta: '5', '1:05', '01:05', '65', '1:05.5'
    """
    if time_str is None:
        return None
    time_str = str(time_str).strip()
    if ':' in time_str:
        parts = time_str.split(':')
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(time_str)


def get_video_info(url):
    """Obtiene metadata del video con yt-dlp."""
    cmd = [
        'yt-dlp', '--dump-json', '--no-playlist', url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def get_video_duration(filepath):
    """Obtiene duracion de un archivo de video/audio con ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(filepath)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return None


def download_video(url, output_path, start=None, end=None):
    """Descarga video de YouTube con yt-dlp + trim con ffmpeg.
    
    Estrategia:
    1. Si hay trim: descarga completo a temp, luego trimea con ffmpeg
    2. Si no hay trim: descarga directo al destino
    
    El video se descarga en la mejor calidad disponible hasta 720p
    (no necesitamos 4K para un clip que ocupa 30% de un 1080x1920).
    """
    log = get_logger()
    
    # Formato de descarga: mejor video+audio hasta 720p
    format_str = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
    
    if start is not None or end is not None:
        # Descargar a temp, luego trimear
        temp_path = TEMP_DIR / f"temp_{uuid.uuid4().hex[:8]}.mp4"
        cmd = [
            'yt-dlp',
            '-f', format_str,
            '--merge-output-format', 'mp4',
            '-o', str(temp_path),
            '--no-playlist',
            url
        ]
        log.info(f"  Descargando video completo...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.error(f"  yt-dlp error: {result.stderr[:200]}")
            return False
        
        # Buscar el archivo descargado (yt-dlp puede cambiar extension)
        actual_temp = None
        for f in TEMP_DIR.glob(f"temp_{temp_path.stem.split('_')[1]}*"):
            actual_temp = f
            break
        if not actual_temp:
            # Buscar cualquier archivo reciente en temp
            files = sorted(TEMP_DIR.glob("temp_*"), key=os.path.getmtime, reverse=True)
            actual_temp = files[0] if files else temp_path
        
        # Trimear con ffmpeg
        ffmpeg_cmd = ['ffmpeg', '-y']
        if start is not None:
            ffmpeg_cmd += ['-ss', str(start)]
        ffmpeg_cmd += ['-i', str(actual_temp)]
        if end is not None:
            if start is not None:
                ffmpeg_cmd += ['-t', str(end - start)]
            else:
                ffmpeg_cmd += ['-t', str(end)]
        
        # Escalar a max 1080 de ancho, mantener aspect ratio, altura par
        ffmpeg_cmd += [
            '-vf', 'scale=min(1080\,iw):-2',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
            '-c:a', 'aac', '-b:a', '128k',
            str(output_path)
        ]
        
        log.info(f"  Trimming: {start}s - {end}s")
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=120)
        
        # Limpiar temp
        if actual_temp.exists():
            actual_temp.unlink()
        
        if result.returncode != 0:
            log.error(f"  ffmpeg error: {result.stderr[:200]}")
            return False
    else:
        # Descarga directa sin trim
        cmd = [
            'yt-dlp',
            '-f', format_str,
            '--merge-output-format', 'mp4',
            '-o', str(output_path),
            '--no-playlist',
            url
        ]
        log.info(f"  Descargando video completo...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            log.error(f"  yt-dlp error: {result.stderr[:200]}")
            return False
    
    return output_path.exists()


def extract_audio(video_path, audio_path):
    """Extrae audio de un video a archivo separado (.mp3)."""
    cmd = [
        'ffmpeg', '-y',
        '-i', str(video_path),
        '-vn',  # sin video
        '-c:a', 'libmp3lame', '-b:a', '192k',
        str(audio_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode == 0


def download_audio_only(url, output_path, start=None, end=None):
    """Descarga solo el audio de un video (para musica de fondo)."""
    log = get_logger()
    
    if start is not None or end is not None:
        # Descargar completo, luego trim audio
        temp_path = TEMP_DIR / f"temp_audio_{uuid.uuid4().hex[:8]}.mp3"
        cmd = [
            'yt-dlp',
            '-f', 'bestaudio',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '192K',
            '-o', str(temp_path),
            '--no-playlist',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            log.error(f"  yt-dlp audio error: {result.stderr[:200]}")
            return False
        
        # Trim con ffmpeg
        ffmpeg_cmd = ['ffmpeg', '-y']
        if start is not None:
            ffmpeg_cmd += ['-ss', str(start)]
        ffmpeg_cmd += ['-i', str(temp_path)]
        if end is not None:
            if start is not None:
                ffmpeg_cmd += ['-t', str(end - start)]
            else:
                ffmpeg_cmd += ['-t', str(end)]
        ffmpeg_cmd += ['-c:a', 'libmp3lame', '-b:a', '192k', str(output_path)]
        
        result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=60)
        if temp_path.exists():
            temp_path.unlink()
        return result.returncode == 0
    else:
        cmd = [
            'yt-dlp',
            '-f', 'bestaudio',
            '--extract-audio',
            '--audio-format', 'mp3',
            '--audio-quality', '192K',
            '-o', str(output_path),
            '--no-playlist',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0


def register_clip(clip_id, filename, url, duration, source_title=None):
    """Registra un clip en la tabla clips de SQLite."""
    db = get_db()
    db.execute("""
        INSERT OR REPLACE INTO clips (id, descripcion, categorias, filename, filename_original, source_path, duracion_s, catalogado_at)
        VALUES (?, ?, '[]', ?, ?, ?, ?, ?)
    """, (
        clip_id,
        source_title or f"Clip de {url}",
        filename,
        source_title or '',
        url,
        duration,
        datetime.now().isoformat()
    ))
    db.commit()


def register_audio(filename, url, duration, source_title=None):
    """Registra un audio en user_feedback como referencia (temporal hasta tener tabla audio)."""
    # Por ahora solo log, en el futuro tabla audio
    log = get_logger()
    log.info(f"  Audio registrado: {filename} ({duration:.1f}s)")


def process_single(url, start=None, end=None, solo_audio=False):
    """Procesa una URL: descarga, trimea, extrae audio, registra."""
    log = get_logger()
    
    # Obtener info del video
    log.info(f"  Obteniendo info: {url[:60]}...")
    info = get_video_info(url)
    title = info.get('title', 'unknown') if info else 'unknown'
    video_id = info.get('id', uuid.uuid4().hex[:8]) if info else uuid.uuid4().hex[:8]
    
    # Generar ID unico para el clip
    clip_id = f"clip_{video_id}_{uuid.uuid4().hex[:4]}"
    
    if solo_audio:
        # Solo descargar audio
        audio_filename = f"{clip_id}.mp3"
        audio_path = AUDIO_DIR / audio_filename
        
        log.info(f"  Descargando solo audio: {title[:50]}")
        success = download_audio_only(url, audio_path, start, end)
        
        if success and audio_path.exists():
            duration = get_video_duration(audio_path) or 0
            register_audio(audio_filename, url, duration, title)
            log.info(f"  -> OK: {audio_filename} ({duration:.1f}s)")
            return True
        else:
            log.error(f"  -> FALLO al descargar audio")
            return False
    
    # Descargar video
    clip_filename = f"{clip_id}.mp4"
    clip_path = CLIPS_DIR / clip_filename
    
    log.info(f"  Descargando: {title[:50]}")
    success = download_video(url, clip_path, start, end)
    
    if not success or not clip_path.exists():
        log.error(f"  -> FALLO al descargar video")
        return False
    
    # Obtener duracion real
    duration = get_video_duration(clip_path) or 0
    
    # Validar duracion minima (2s) y maxima (30s)
    if duration < 2:
        log.warning(f"  -> Clip muy corto ({duration:.1f}s), guardando de todos modos")
    if duration > 30:
        log.warning(f"  -> Clip largo ({duration:.1f}s), considera trimear mas")
    
    # Extraer audio por separado
    audio_filename = f"{clip_id}.mp3"
    audio_path = AUDIO_DIR / audio_filename
    extract_audio(clip_path, audio_path)
    
    # Registrar en DB
    register_clip(clip_id, clip_filename, url, duration, title)
    
    log.info(f"  -> OK: {clip_filename} ({duration:.1f}s) + audio extraido")
    return True


def process_batch(batch_file):
    """Procesa un archivo batch con multiples URLs."""
    log = get_logger()
    path = Path(batch_file)
    
    if not path.exists():
        log.error(f"Archivo batch no encontrado: {batch_file}")
        return
    
    lines = path.read_text(encoding='utf-8').strip().split('\n')
    entries = []
    
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        url = parts[0]
        start = parse_time(parts[1]) if len(parts) > 1 else None
        end = parse_time(parts[2]) if len(parts) > 2 else None
        entries.append((url, start, end))
    
    log.info(f"Batch: {len(entries)} clips por descargar")
    
    ok = 0
    fail = 0
    for i, (url, start, end) in enumerate(entries, 1):
        log.info(f"\n[{i}/{len(entries)}]")
        success = process_single(url, start, end)
        if success:
            ok += 1
        else:
            fail += 1
    
    log.info(f"\nBatch completado: {ok} OK, {fail} fallos")


def main():
    parser = argparse.ArgumentParser(description="Descargar clips de reaccion de YouTube")
    parser.add_argument('url', nargs='?', default=None,
                        help="URL del video de YouTube")
    parser.add_argument('--start', '-s', default=None,
                        help="Tiempo de inicio (segundos o mm:ss)")
    parser.add_argument('--end', '-e', default=None,
                        help="Tiempo de fin (segundos o mm:ss)")
    parser.add_argument('--solo-audio', action='store_true',
                        help="Descargar solo el audio (para musica de fondo)")
    parser.add_argument('--batch', '-b', default=None,
                        help="Archivo .txt con URLs (una por linea)")
    args = parser.parse_args()
    
    # Setup
    load_config()
    init_db()
    setup_logger('descargar_clips')
    log = get_logger()
    ensure_dirs()
    
    log.info("=== DESCARGAR CLIPS - INICIO ===")
    
    if args.batch:
        process_batch(args.batch)
    elif args.url:
        start = parse_time(args.start)
        end = parse_time(args.end)
        process_single(args.url, start, end, args.solo_audio)
    else:
        parser.print_help()
        print("\nEjemplos:")
        print('  python descargar_clips.py "https://youtube.com/watch?v=XXX" --start 5 --end 12')
        print('  python descargar_clips.py "https://youtube.com/watch?v=XXX" --solo-audio')
        print('  python descargar_clips.py --batch clips_pendientes.txt')
    
    log.info("=== DESCARGAR CLIPS - FIN ===")


if __name__ == "__main__":
    main()
