#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Catalogo Visual de Clips (V2 completo)

Interfaz HTML para ver, editar y aprobar clips de reaccion.
Con audio, timestamp, pre-escucha de audios, trim visual, y 3 estados.

Requisitos:
    ffmpeg en PATH (para generar thumbnails, trim, audio swap)

Uso:
    python catalogo_clips.py                    # Ver todos los clips
    python catalogo_clips.py --pendientes       # Solo clips sin aprobar
    python catalogo_clips.py --apply            # Aplicar decisiones (trim, audio, etc)
    python catalogo_clips.py --generar-thumbs   # Regenerar thumbnails

Acciones por clip (3 estados):
    - APROBAR: Listo para match (borde verde)
    - CAMBIOS: Solicitar trim/audio/re-descarga (borde naranja)
    - RECHAZAR: No sirve (borde rojo, se mueve a rejected/)

Post-apply:
    - Clips aprobados se marcan en DB
    - Clips con cambios se procesan (trim/audio) y quedan pendientes para re-revisar
    - Clips rechazados se mueven a clips/rejected/
"""

import sys
import os
import json
import argparse
import subprocess
import webbrowser
import http.server
import threading
import time
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db
from utils.config import load_config
from utils.logger import setup_logger, get_logger

CLIPS_DIR = SCRIPT_DIR / "clips"
AUDIO_DIR = SCRIPT_DIR / "audio"
THUMBS_DIR = SCRIPT_DIR / "clips" / "thumbs"
CATALOG_HTML = SCRIPT_DIR / "catalogo_clips.html"
CATALOG_RESULTS = SCRIPT_DIR / "catalogo_results.json"
SERVER_PORT = 8767


def ensure_dirs():
    CLIPS_DIR.mkdir(exist_ok=True)
    AUDIO_DIR.mkdir(exist_ok=True)
    THUMBS_DIR.mkdir(exist_ok=True)


def generate_thumbnail(video_path, thumb_path, time_offset=1):
    """Genera thumbnail JPG de un frame del video."""
    cmd = [
        'ffmpeg', '-y', '-ss', str(time_offset),
        '-i', str(video_path),
        '-vframes', '1', '-q:v', '3',
        '-vf', 'scale=320:-2',
        str(thumb_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.returncode == 0


def get_video_duration(filepath):
    cmd = [
        'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(filepath)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return None


def get_video_resolution(filepath):
    cmd = [
        'ffprobe', '-v', 'quiet',
        '-show_entries', 'stream=width,height',
        '-select_streams', 'v:0',
        '-of', 'csv=p=0', str(filepath)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        parts = result.stdout.strip().split(',')
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    return None, None


def get_all_clips(only_pending=False, only_ia=False):
    """Lee clips de la DB."""
    db = get_db()
    
    # Asegurar columna 'approved' existe
    try:
        db.execute("ALTER TABLE clips ADD COLUMN approved INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass
    
    query = """
        SELECT id, descripcion, categorias, filename, source_path, duracion_s, 
               usado_count, catalogado_at, approved,
               mood, intensidad, audio_analisis, timing, recomendaciones,
               compatibilidad_meme, descripcion_corta, categorizado_ia_at
        FROM clips
    """
    if only_pending:
        query += " WHERE COALESCE(approved, 0) = 0"
    elif only_ia:
        query += " WHERE categorizado_ia_at IS NOT NULL"
    query += " ORDER BY catalogado_at DESC"
    
    rows = db.execute(query).fetchall()
    
    clips = []
    for row in rows:
        clip_path = CLIPS_DIR / row['filename']
        if not clip_path.exists():
            continue
        
        thumb_path = THUMBS_DIR / (clip_path.stem + '.jpg')
        if not thumb_path.exists():
            generate_thumbnail(clip_path, thumb_path)
        
        w, h = get_video_resolution(clip_path)
        cats = json.loads(row['categorias']) if row['categorias'] else []
        
        # Parse IA JSON fields
        audio_info = {}
        timing_info = {}
        recs_info = {}
        compat_list = []
        try:
            audio_info = json.loads(row['audio_analisis']) if row['audio_analisis'] else {}
        except Exception:
            pass
        try:
            timing_info = json.loads(row['timing']) if row['timing'] else {}
        except Exception:
            pass
        try:
            recs_info = json.loads(row['recomendaciones']) if row['recomendaciones'] else {}
        except Exception:
            pass
        try:
            compat_list = json.loads(row['compatibilidad_meme']) if row['compatibilidad_meme'] else []
        except Exception:
            pass
        
        clips.append({
            'id': row['id'],
            'descripcion': row['descripcion'] or '',
            'descripcion_corta': row['descripcion_corta'] or '',
            'categorias': cats,
            'filename': row['filename'],
            'source_url': row['source_path'] or '',
            'duracion': row['duracion_s'] or 0,
            'usado_count': row['usado_count'] or 0,
            'catalogado_at': row['catalogado_at'] or '',
            'approved': row['approved'] or 0,
            'has_thumb': thumb_path.exists(),
            'width': w,
            'height': h,
            'orientation': 'H' if (w and h and w > h) else 'V' if (w and h) else '?',
            'mood': row['mood'] or '',
            'intensidad': row['intensidad'] or 0,
            'audio_info': audio_info,
            'timing_info': timing_info,
            'recs_info': recs_info,
            'compat_list': compat_list,
            'categorizado': bool(row['categorizado_ia_at']),
        })
    
    return clips


def get_available_audios():
    """Lista todos los .mp3 en audio/."""
    audios = []
    for f in sorted(AUDIO_DIR.glob('*.mp3')):
        dur = get_video_duration(f)
        audios.append({
            'filename': f.name,
            'duracion': dur or 0,
        })
    return audios


def generate_html(clips, audios):
    """Genera HTML completo del catalogo."""
    
    cards = []
    for c in clips:
        cid = c['id']
        dur_str = f"{c['duracion']:.1f}s" if c['duracion'] else '?'
        res_str = f"{c['width']}x{c['height']}" if c['width'] else '?'
        orient = c['orientation']
        
        # Pre-mark approved clips
        card_class = 'card marked-ok' if c['approved'] else 'card'
        
        # Tags pills
        tags_html = ''
        for tag in c['categorias']:
            tags_html += '<span class="tag">' + tag + '</span>'
        if not tags_html:
            tags_html = '<span class="tag empty">sin tags</span>'
        
        thumb_src = f"clips/thumbs/{Path(c['filename']).stem}.jpg" if c['has_thumb'] else ''
        
        # Audio options for dropdown
        audio_options = '<option value="">-- Audio original --</option>'
        for a in audios:
            audio_options += '<option value="' + a['filename'] + '">' + a['filename'][:30] + ' (' + f"{a['duracion']:.1f}s" + ')</option>'
        
        desc_safe = c['descripcion'].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        url_safe = c['source_url'].replace('"', '&quot;') if c['source_url'] else ''
        
        # Build IA analysis section (only if categorized)
        ia_section = ''
        if c.get('categorizado'):
            ai = c.get('audio_info', {})
            ti = c.get('timing_info', {})
            rc = c.get('recs_info', {})
            cp = c.get('compat_list', [])
            
            ia_parts = []
            ia_parts.append('<div class="ia-section">')
            
            # Audio
            audio_tipo = ai.get('tipo', '?')
            audio_desc = ai.get('descripcion', '').replace('"', '&quot;').replace('<', '&lt;')
            audio_energia = ai.get('energia_audio', '?')
            beat = 'Si' if ai.get('tiene_beat_drop') else 'No'
            ia_parts.append('<div class="ia-row"><b>Audio:</b> [' + audio_tipo + '] ' + audio_desc + '</div>')
            ia_parts.append('<div class="ia-row"><b>Energia:</b> ' + audio_energia + ' | Beat drop: ' + beat + '</div>')
            
            # Timing
            punch = str(ti.get('punch_moment_s', '?'))
            mejor = str(ti.get('mejor_rango_s', '?'))
            muerto = ti.get('inicio_muerto_s', 0)
            ia_parts.append('<div class="ia-row"><b>Punch:</b> @' + punch + 's | Mejor rango: ' + mejor + '</div>')
            if muerto and muerto > 0:
                ia_parts.append('<div class="ia-row ia-warn"><b>Inicio muerto:</b> ' + str(muerto) + 's</div>')
            
            # Recomendaciones
            recortar = rc.get('recortar', 'No')
            audio_sirve = 'Si' if rc.get('audio_original_sirve', True) else 'No'
            audio_sug = rc.get('audio_sugerencia', '').replace('"', '&quot;').replace('<', '&lt;')
            meme_ideal = rc.get('meme_ideal', '').replace('"', '&quot;').replace('<', '&lt;')
            ia_parts.append('<div class="ia-row"><b>Recortar:</b> ' + recortar + '</div>')
            ia_parts.append('<div class="ia-row"><b>Audio sirve:</b> ' + audio_sirve + '</div>')
            if audio_sirve == 'No':
                ia_parts.append('<div class="ia-row ia-suggest"><b>Sugerencia:</b> ' + audio_sug + '</div>')
            ia_parts.append('<div class="ia-row"><b>Meme ideal:</b> ' + meme_ideal + '</div>')
            
            # Compatibilidad
            if cp:
                ia_parts.append('<div class="ia-row"><b>Compatible con:</b> ' + ' | '.join(str(x).replace('<','&lt;') for x in cp[:3]) + '</div>')
            
            ia_parts.append('</div>')
            ia_section = ''.join(ia_parts)
        
        dur_class = 'dur-ok' if 3 <= c['duracion'] <= 12 else 'dur-warn' if 2 <= c['duracion'] < 3 or 12 < c['duracion'] <= 20 else 'dur-bad'
        card = (
            '<div class="' + card_class + '" id="c-' + cid + '" data-id="' + cid + '">'
            '<div class="card-top">'
            '<video class="preview" src="clips/' + c['filename'] + '" poster="' + thumb_src + '" preload="metadata" onclick="togglePlay(this)" loop></video>'
            '<div class="time-display" id="time-' + cid + '">0:00 / ' + dur_str + '</div>'
            '<div class="progress-bar" onclick="seekVideo(event,\'' + cid + '\')"><div class="progress-fill" id="prog-' + cid + '"></div></div>'
            '<div class="card-actions">'
            '<button class="btn-ok" onclick="markOk(\'' + cid + '\')">APROBAR</button>'
            '<button class="btn-ch" onclick="markChanges(\'' + cid + '\')">CAMBIOS</button>'
            '<button class="btn-no" onclick="markReject(\'' + cid + '\')">RECHAZAR</button>'
            '<button class="btn-rp" onclick="markReprocess(\'' + cid + '\')">RECORTAR</button>'
            '</div>'
            '<div class="dur ' + dur_class + '">' + dur_str + ' | ' + orient + ' | ' + res_str + '</div>'
            '</div>'
            '<div class="card-body">'
            '<div class="card-header">'
            '<span class="clip-id">' + cid[:25] + '</span>'
            + ('<span class="mood-badge mood-' + c['mood'] + '">' + c['mood'] + ' ' + str(c['intensidad']) + '/10</span>' if c.get('categorizado') else '') +
            '</div>'
            '<div class="desc">' + desc_safe + '</div>'
            '<div class="tags">' + tags_html + '</div>'
            + ia_section
            + (('<div class="src-url"><a href="' + url_safe + '" target="_blank">YouTube link</a> <button class="btn-redownload" onclick="copyUrl(\'' + url_safe + '\')">Copiar URL</button></div>') if url_safe else '') +
            '<details><summary>Editar (trim / audio)</summary>'
            '<div class="edit-section">'
            '<label>Trim (segundos):</label>'
            '<div class="trim-row">'
            '<input type="number" class="trim-start" data-id="' + cid + '" placeholder="inicio" step="0.5" min="0" value="0">'
            '<span class="trim-sep">a</span>'
            '<input type="number" class="trim-end" data-id="' + cid + '" placeholder="fin" step="0.5" max="' + f"{c['duracion']:.1f}" + '" value="' + f"{c['duracion']:.1f}" + '">'
            '</div>'
            '<label>Reemplazar audio:</label>'
            '<select class="audio-select" data-id="' + cid + '">' + audio_options + '</select>'
            '<button class="btn-listen" onclick="listenAudio(this.previousElementSibling.value)">Escuchar audio</button>'
            '</div>'
            '</details>'
            '<div class="vol-row"><span>Vol:</span><input type="range" min="0" max="100" value="50" oninput="setVol(\'' + cid + '\',this.value)"><span class="speed-btns"><button onclick="setSpeed(\'' + cid + '\',0.5)">0.5x</button><button class="active" onclick="setSpeed(\'' + cid + '\',1)">1x</button><button onclick="setSpeed(\'' + cid + '\',1.5)">1.5x</button><button onclick="setSpeed(\'' + cid + '\',2)">2x</button></span></div>'
            '<textarea class="notes" placeholder="Notas (ej: recortar del 0:03 al 0:08)..." data-id="' + cid + '"></textarea>'
            '</div>'
            '</div>'
        )
        cards.append(card)
    
    cards_html = '\n'.join(cards)
    total = str(len(clips))
    approved_count = sum(1 for c in clips if c['approved'])
    pending_count = len(clips) - approved_count
    avg_dur = sum(c['duracion'] for c in clips) / len(clips) if clips else 0
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>Catalogo Clips - ' + total + '</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,sans-serif;background:#0f0f1a;color:#eee;padding:20px}')
    html_parts.append('.hdr{text-align:center;margin-bottom:20px;padding:15px;background:#1a1a2e;border-radius:10px}')
    html_parts.append('.hdr h1{font-size:1.4em;margin-bottom:8px}')
    html_parts.append('.stats{display:flex;justify-content:center;gap:12px;font-size:0.85em;flex-wrap:wrap}')
    html_parts.append('.stats span{padding:4px 12px;border-radius:15px;background:#0f3460}')
    html_parts.append('.tb{display:flex;justify-content:center;gap:10px;margin-bottom:20px;flex-wrap:wrap}')
    html_parts.append('.tb button{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:0.95em;font-weight:bold}')
    html_parts.append('.sv{background:#00d4aa;color:#000}')
    html_parts.append('.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:15px}')
    html_parts.append('.card{background:#1a1a2e;border-radius:10px;overflow:hidden;border:2px solid transparent;transition:all 0.2s}')
    html_parts.append('.card.marked-ok{border-color:#4CAF50;opacity:0.8}')
    html_parts.append('.card.marked-changes{border-color:#ff9800}')
    html_parts.append('.card.marked-reject{border-color:#f44336;opacity:0.4}')
    html_parts.append('.card-top{position:relative}')
    html_parts.append('.preview{width:100%;height:220px;object-fit:contain;background:#000;display:block;cursor:pointer}')
    html_parts.append('.time-display{position:absolute;bottom:35px;left:5px;background:rgba(0,0,0,0.8);padding:2px 8px;border-radius:4px;font-size:0.75em;font-family:monospace}')
    html_parts.append('.card-actions{position:absolute;top:5px;right:5px;display:flex;gap:4px}')
    html_parts.append('.card-actions button{padding:5px 8px;border:none;border-radius:5px;cursor:pointer;font-size:0.7em;font-weight:bold}')
    html_parts.append('.btn-ok{background:#4CAF50;color:white}')
    html_parts.append('.btn-ch{background:#ff9800;color:white}')
    html_parts.append('.btn-no{background:#f44336;color:white}')
    html_parts.append('.btn-rp{background:#9C27B0;color:white}')
    html_parts.append('.card.marked-reprocess{border-color:#9C27B0;opacity:0.7}')
    html_parts.append('.btn-listen{margin-top:4px;padding:4px 10px;border:none;border-radius:4px;background:#2196F3;color:white;cursor:pointer;font-size:0.75em}')
    html_parts.append('.dur{position:absolute;bottom:5px;right:5px;background:rgba(0,0,0,0.7);padding:2px 6px;border-radius:4px;font-size:0.7em}')
    html_parts.append('.card-body{padding:10px}')
    html_parts.append('.card-header{display:flex;align-items:center;gap:8px;margin-bottom:4px}')
    html_parts.append('.clip-id{font-family:monospace;font-size:0.65em;color:#aaa}')
    html_parts.append('.desc{font-size:0.78em;color:#ccc;margin-bottom:5px;line-height:1.4;max-height:80px;overflow-y:auto}')
    html_parts.append('.tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px}')
    html_parts.append('.tag{font-size:0.65em;padding:2px 6px;background:#16213e;border-radius:10px;color:#00d4aa}')
    html_parts.append('.tag.empty{color:#666}')
    html_parts.append('.src-url{margin-bottom:6px}')
    html_parts.append('.src-url a{font-size:0.75em;color:#2196F3;text-decoration:none}')
    html_parts.append('.src-url a:hover{text-decoration:underline}')
    html_parts.append('details{margin-top:5px}')
    html_parts.append('summary{cursor:pointer;font-size:0.8em;color:#00d4aa}')
    html_parts.append('.edit-section{margin-top:8px;display:flex;flex-direction:column;gap:6px}')
    html_parts.append('.edit-section label{font-size:0.75em;color:#aaa}')
    html_parts.append('.trim-row{display:flex;gap:5px;align-items:center}')
    html_parts.append('.trim-row input{width:70px;padding:4px;border:1px solid #333;border-radius:4px;background:#0f0f1a;color:#eee;font-size:0.8em}')
    html_parts.append('.trim-sep{color:#666;font-size:0.8em}')
    html_parts.append('.audio-select{padding:4px;border:1px solid #333;border-radius:4px;background:#0f0f1a;color:#eee;font-size:0.8em;width:100%}')
    html_parts.append('.notes{width:100%;height:35px;padding:5px;border:1px solid #333;border-radius:5px;background:#0a0a15;color:#eee;font-size:0.8em;resize:vertical;margin-top:5px}')
    html_parts.append('#audio-player{position:fixed;bottom:20px;right:20px;background:#1a1a2e;padding:15px;border-radius:10px;border:1px solid #333;display:none;z-index:100}')
    html_parts.append('#audio-player .close-btn{position:absolute;top:5px;right:8px;cursor:pointer;color:#f44336;font-size:1.2em}')
    html_parts.append('.ia-section{margin-top:6px;padding:6px 8px;background:#0a0a15;border-radius:6px;border:1px solid #1a2a3a;font-size:0.72em;line-height:1.5}')
    html_parts.append('.ia-row{margin-bottom:2px;color:#bbb}')
    html_parts.append('.ia-row b{color:#00d4aa}')
    html_parts.append('.ia-warn{color:#ff9800}')
    html_parts.append('.ia-suggest{color:#2196F3;font-style:italic}')
    html_parts.append('.mood-badge{padding:2px 8px;border-radius:10px;font-size:0.7em;font-weight:bold;margin-left:6px}')
    html_parts.append('.mood-epico{background:#9C27B0;color:white}')
    html_parts.append('.mood-chill{background:#4CAF50;color:white}')
    html_parts.append('.mood-caotico{background:#f44336;color:white}')
    html_parts.append('.mood-dramatico{background:#FF5722;color:white}')
    html_parts.append('.mood-comico{background:#FFC107;color:#000}')
    html_parts.append('.mood-tenso{background:#795548;color:white}')
    html_parts.append('.mood-nostalgico{background:#607D8B;color:white}')
    html_parts.append('.mood-energetico{background:#FF9800;color:white}')
    html_parts.append('.dur-ok{background:rgba(76,175,80,0.8)}')
    html_parts.append('.dur-warn{background:rgba(255,152,0,0.8)}')
    html_parts.append('.dur-bad{background:rgba(244,67,54,0.8)}')
    html_parts.append('.btn-redownload{padding:2px 6px;border:none;border-radius:3px;background:#555;color:#eee;cursor:pointer;font-size:0.7em;margin-left:5px}')
    html_parts.append('.filters{display:flex;justify-content:center;gap:10px;margin-bottom:15px;flex-wrap:wrap;align-items:center}')
    html_parts.append('.filters input,.filters select{padding:6px 10px;border:1px solid #333;border-radius:6px;background:#0f0f1a;color:#eee;font-size:0.85em}')
    html_parts.append('.filters input{width:200px}')
    html_parts.append('.filters select{width:150px}')
    html_parts.append('.card-top .progress-bar{position:absolute;bottom:30px;left:0;right:0;height:4px;background:#333;cursor:pointer}')
    html_parts.append('.card-top .progress-fill{height:100%;background:#00d4aa;width:0%;pointer-events:none}')
    html_parts.append('.vol-row{display:flex;align-items:center;gap:5px;margin-top:4px}')
    html_parts.append('.vol-row input[type=range]{width:80px;height:3px}')
    html_parts.append('.vol-row span{font-size:0.7em;color:#888}')
    html_parts.append('.speed-btns{display:flex;gap:3px;margin-top:3px}')
    html_parts.append('.speed-btns button{padding:2px 5px;border:none;border-radius:3px;background:#16213e;color:#aaa;cursor:pointer;font-size:0.65em}')
    html_parts.append('.speed-btns button.active{background:#00d4aa;color:#000}')
    html_parts.append('.fullscreen-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.95);z-index:200;display:none;align-items:center;justify-content:center}')
    html_parts.append('.fullscreen-overlay video{max-width:90%;max-height:90%}')
    html_parts.append('.fullscreen-overlay .close-fs{position:absolute;top:20px;right:30px;font-size:2em;color:white;cursor:pointer}')
    html_parts.append('.kb-hint{text-align:center;font-size:0.75em;color:#555;margin-bottom:10px}')
    html_parts.append('</style></head><body>')
    
    # Header
    html_parts.append('<div class="hdr">')
    html_parts.append('<h1>Catalogo de Clips</h1>')
    html_parts.append('<div class="stats">')
    html_parts.append('<span>Total: ' + total + '</span>')
    html_parts.append('<span>Ya aprobados: ' + str(approved_count) + '</span>')
    html_parts.append('<span>Pendientes: ' + str(pending_count) + '</span>')
    html_parts.append('<span>Dur promedio: ' + f"{avg_dur:.1f}s" + '</span>')
    html_parts.append('<span>Audios: ' + str(len(audios)) + '</span>')
    html_parts.append('<span id="sok">OK: 0</span>')
    html_parts.append('<span id="sch">Cambios: 0</span>')
    html_parts.append('<span id="srj">Rechazar: 0</span><span id="srp">Recortar: 0</span>')
    html_parts.append('</div></div>')
    
    # Filters
    html_parts.append('<div class="filters">')
    html_parts.append('<input type="text" id="searchBox" placeholder="Buscar por descripcion..." oninput="filterCards()">')
    html_parts.append('<select id="sortBy" onchange="sortCards()">')
    html_parts.append('<option value="date">Mas recientes</option>')
    html_parts.append('<option value="dur-asc">Duracion (corto a largo)</option>')
    html_parts.append('<option value="dur-desc">Duracion (largo a corto)</option>')
    html_parts.append('<option value="status">Sin decidir primero</option>')
    html_parts.append('</select>')
    html_parts.append('<select id="filterOrient" onchange="filterCards()">')
    html_parts.append('<option value="all">Todas orientaciones</option>')
    html_parts.append('<option value="H">Solo Horizontal</option>')
    html_parts.append('<option value="V">Solo Vertical</option>')
    html_parts.append('</select>')
    html_parts.append('</div>')
    
    # Toolbar
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveResults()">GUARDAR DECISIONES</button>')
    html_parts.append('<button style="background:#555;color:#fff" onclick="unmuteAll()">ACTIVAR AUDIO</button>')
    html_parts.append('<button style="background:#4CAF50;color:#fff" onclick="bulkApprove()">APROBAR TODOS</button>')
    html_parts.append('<button style="background:#f44336;color:#fff" onclick="bulkReject()">RECHAZAR TODOS</button>')
    html_parts.append('<button style="background:#333;color:#fff" onclick="resetAll()">RESET</button>')
    html_parts.append('</div>')
    html_parts.append('<div class="kb-hint">Click = play/pause | Doble click = fullscreen | Scroll bar = seek</div>')
    
    # Grid
    html_parts.append('<div class="grid">' + cards_html + '</div>')
    
    # Audio player (fixed bottom-right)
    html_parts.append('<div id="audio-player"><span class="close-btn" onclick="stopAudio()">X</span><div id="ap-name"></div><audio id="ap-audio" controls></audio></div>')
    html_parts.append('<div class="fullscreen-overlay" id="fs-overlay" onclick="closeFullscreen()"><span class="close-fs" onclick="closeFullscreen()">X</span><video id="fs-video" controls loop></video></div>')
    
    # JavaScript
    html_parts.append('<script>')
    # Pre-populate D with already approved
    d_parts = []
    for c in clips:
        if c['approved']:
            d_parts.append('"' + c['id'] + '":"ok"')
    html_parts.append('var D={' + ','.join(d_parts) + '};var notes={};var trims={};var audios_map={};')
    html_parts.append('function markOk(id){D[id]="ok";document.getElementById("c-"+id).className="card marked-ok";upd();}')
    html_parts.append('function markChanges(id){D[id]="changes";document.getElementById("c-"+id).className="card marked-changes";upd();}')
    html_parts.append('function markReject(id){D[id]="reject";document.getElementById("c-"+id).className="card marked-reject";upd();}')
    html_parts.append('function markReprocess(id){D[id]="reprocess";document.getElementById("c-"+id).className="card marked-reprocess";upd();}')
    html_parts.append('function upd(){')
    html_parts.append('var ok=0,ch=0,rj=0,rp=0;for(var k in D){if(D[k]==="ok")ok++;if(D[k]==="changes")ch++;if(D[k]==="reject")rj++;if(D[k]==="reprocess")rp++;}')
    html_parts.append('document.getElementById("sok").textContent="OK: "+ok;')
    html_parts.append('document.getElementById("sch").textContent="Cambios: "+ch;')
    html_parts.append('document.getElementById("srj").textContent="Rechazar: "+rj;')
    html_parts.append('document.getElementById("srp").textContent="Recortar: "+rp;}')
    # Toggle play with timestamp update
    html_parts.append('function togglePlay(v){if(v.paused){v.play()}else{v.pause()}}')
    html_parts.append('document.querySelectorAll(".preview").forEach(function(v){')
    html_parts.append('v.addEventListener("timeupdate",function(){')
    html_parts.append('var id=this.closest(".card").dataset.id;')
    html_parts.append('var cur=Math.floor(this.currentTime);var dur=Math.floor(this.duration||0);')
    html_parts.append('var mm=Math.floor(cur/60);var ss=("0"+(cur%60)).slice(-2);')
    html_parts.append('var dm=Math.floor(dur/60);var ds=("0"+(dur%60)).slice(-2);')
    html_parts.append('document.getElementById("time-"+id).textContent=mm+":"+ss+" / "+dm+":"+ds;')
    html_parts.append('});});')
    # Unmute all
    html_parts.append('function unmuteAll(){document.querySelectorAll(".preview").forEach(function(v){v.muted=false;v.volume=0.5;});alert("Audio activado en todos los clips");}')
    # Listen audio preview
    html_parts.append('function listenAudio(filename){if(!filename){alert("Selecciona un audio primero");return;}')
    html_parts.append('var player=document.getElementById("audio-player");var audio=document.getElementById("ap-audio");')
    html_parts.append('audio.src="audio/"+filename;audio.play();')
    html_parts.append('document.getElementById("ap-name").textContent=filename;')
    html_parts.append('player.style.display="block";}')
    html_parts.append('function stopAudio(){var audio=document.getElementById("ap-audio");audio.pause();document.getElementById("audio-player").style.display="none";}')
    # Save
    # Extra JS: seek, volume, speed, filter, sort, fullscreen, bulk
    html_parts.append('function seekVideo(e,id){var bar=e.currentTarget;var rect=bar.getBoundingClientRect();var pct=(e.clientX-rect.left)/rect.width;var v=document.querySelector("#c-"+id+" .preview");v.currentTime=pct*v.duration;}')
    html_parts.append('function setVol(id,val){document.querySelector("#c-"+id+" .preview").volume=val/100;}')
    html_parts.append('function setSpeed(id,s){var v=document.querySelector("#c-"+id+" .preview");v.playbackRate=s;var btns=v.closest(".card").querySelectorAll(".speed-btns button");btns.forEach(function(b){b.classList.remove("active");if(parseFloat(b.textContent)===s)b.classList.add("active");});}')
    html_parts.append('function copyUrl(url){navigator.clipboard.writeText(url);alert("URL copiada al clipboard");}')
    html_parts.append('function bulkApprove(){document.querySelectorAll(".card").forEach(function(c){if(c.style.display!=="none"&&!D[c.dataset.id])markOk(c.dataset.id);});}')
    html_parts.append('function bulkReject(){document.querySelectorAll(".card").forEach(function(c){if(c.style.display!=="none"&&!D[c.dataset.id])markReject(c.dataset.id);});}')
    html_parts.append('function resetAll(){D={};document.querySelectorAll(".card").forEach(function(c){c.className="card";});upd();}')
    html_parts.append('function filterCards(){var q=document.getElementById("searchBox").value.toLowerCase();var o=document.getElementById("filterOrient").value;document.querySelectorAll(".card").forEach(function(c){var desc=c.querySelector(".desc").textContent.toLowerCase();var dur=c.querySelector(".dur").textContent;var matchQ=!q||desc.indexOf(q)>=0;var matchO=o==="all"||dur.indexOf("| "+o+" |")>=0;c.style.display=(matchQ&&matchO)?"":"none";});}')
    html_parts.append('function sortCards(){var s=document.getElementById("sortBy").value;var grid=document.querySelector(".grid");var cards=Array.from(grid.children);cards.sort(function(a,b){if(s==="dur-asc")return parseFloat(a.querySelector(".dur").textContent)-parseFloat(b.querySelector(".dur").textContent);if(s==="dur-desc")return parseFloat(b.querySelector(".dur").textContent)-parseFloat(a.querySelector(".dur").textContent);if(s==="status"){var aD=D[a.dataset.id]?1:0;var bD=D[b.dataset.id]?1:0;return aD-bD;}return 0;});cards.forEach(function(c){grid.appendChild(c);});}')
    # Fullscreen on double-click
    html_parts.append('document.querySelectorAll(".preview").forEach(function(v){v.addEventListener("dblclick",function(e){e.preventDefault();var fs=document.getElementById("fs-overlay");var fv=document.getElementById("fs-video");fv.src=this.src;fv.currentTime=this.currentTime;fs.style.display="flex";fv.play();});});')
    html_parts.append('function closeFullscreen(){var fs=document.getElementById("fs-overlay");var fv=document.getElementById("fs-video");fv.pause();fs.style.display="none";}')
    # Progress bar update (add to existing timeupdate)
    html_parts.append('document.querySelectorAll(".preview").forEach(function(v){v.addEventListener("timeupdate",function(){var id=this.closest(".card").dataset.id;var pct=(this.currentTime/this.duration)*100;var bar=document.getElementById("prog-"+id);if(bar)bar.style.width=pct+"%";});});')
    html_parts.append('function saveResults(){')
    html_parts.append('document.querySelectorAll(".notes").forEach(function(ta){if(ta.value.trim())notes[ta.dataset.id]=ta.value.trim();});')
    html_parts.append('document.querySelectorAll(".trim-start").forEach(function(inp){var id=inp.dataset.id;var s=parseFloat(inp.value)||0;var eInp=document.querySelector(\'.trim-end[data-id="\'+id+\'"]\');var e=parseFloat(eInp.value)||0;if(s>0||e<parseFloat(eInp.max)){trims[id]={start:s,end:e};}});')
    html_parts.append('document.querySelectorAll(".audio-select").forEach(function(sel){if(sel.value)audios_map[sel.dataset.id]=sel.value;});')
    html_parts.append('var t=Object.keys(D).length;')
    html_parts.append('var data={timestamp:new Date().toISOString(),total_decisions:t,decisions:D,feedback:notes,trims:trims,audio_assignments:audios_map};')
    html_parts.append('var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('a.href=url;a.download="catalogo_results.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('var ch=0;for(var k in D)if(D[k]==="changes")ch++;')
    html_parts.append('var msg="Guardado: "+t+" decisiones, "+Object.keys(trims).length+" trims, "+Object.keys(audios_map).length+" audios.";')
    html_parts.append('if(ch>0)msg+="\\n\\n"+ch+" clips con cambios solicitados. Seran procesados con --apply.";')
    html_parts.append('msg+="\\n\\nCorre: python catalogo_clips.py --apply";')
    html_parts.append('alert(msg);}')
    html_parts.append('upd();')
    html_parts.append('console.log("CatalogoClips OK: "+document.querySelectorAll(".card").length+" clips");')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


def start_local_server():
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def apply_results(results_path=None):
    """Aplica decisiones: aprobar/cambios/rechazar + trim + audio."""
    # Ensure needs_crop column exists
    try:
        db.execute("ALTER TABLE clips ADD COLUMN needs_crop INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass
    log = get_logger()
    path = Path(results_path) if results_path else CATALOG_RESULTS
    downloads_path = Path.home() / "Downloads" / "catalogo_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
    else:
        log.error("No se encontro catalogo_results.json")
        return
    
    decisions = data.get('decisions', {})
    trims = data.get('trims', {})
    audio_assignments = data.get('audio_assignments', {})
    feedback = data.get('feedback', {})
    db = get_db()
    
    ok_count = 0
    changes_count = 0
    reject_count = 0
    reprocess_count = 0
    trim_count = 0
    audio_count = 0
    
    # 1. Aplicar decisiones
    for clip_id, decision in decisions.items():
        if decision == 'ok':
            db.execute("UPDATE clips SET approved = 1 WHERE id = ?", (clip_id,))
            ok_count += 1
        elif decision == 'changes':
            # Marcar como no aprobado (se procesaran cambios abajo)
            db.execute("UPDATE clips SET approved = 0 WHERE id = ?", (clip_id,))
            changes_count += 1
        elif decision == 'reject':
            clip_row = db.execute("SELECT filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
            if clip_row:
                rejected_dir = CLIPS_DIR / "rejected"
                rejected_dir.mkdir(exist_ok=True)
                src = CLIPS_DIR / clip_row['filename']
                if src.exists():
                    src.rename(rejected_dir / clip_row['filename'])
                # Borrar dependencias primero (matches que usan este clip)
            db.execute("DELETE FROM matches WHERE clip_id = ?", (clip_id,))
            db.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            reject_count += 1
        elif decision == 'reprocess':
            # Marcar para recorte en preprocess_clips.py
            # Si hay backup en originals/, restaurar original primero
            clip_row = db.execute("SELECT filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
            if clip_row:
                originals_dir = CLIPS_DIR / "originals"
                backup = originals_dir / clip_row['filename']
                current = CLIPS_DIR / clip_row['filename']
                if backup.exists():
                    # Restaurar original para re-procesar desde cero
                    if current.exists():
                        current.unlink()
                    import shutil
                    shutil.copy2(backup, current)
            db.execute("UPDATE clips SET needs_crop = 1, preprocessed = 0, crop_applied = NULL WHERE id = ?", (clip_id,))
            reprocess_count += 1
    
    # 2. Aplicar trims (solo para clips con decision 'changes')
    for clip_id, trim_data in trims.items():
        clip_row = db.execute("SELECT filename, duracion_s FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip_row:
            continue
        
        src_path = CLIPS_DIR / clip_row['filename']
        if not src_path.exists():
            continue
        
        start = trim_data.get('start', 0)
        end = trim_data.get('end', clip_row['duracion_s'])
        
        # Solo trimear si realmente hay cambio
        if start <= 0.1 and abs(end - (clip_row['duracion_s'] or 0)) < 0.5:
            continue
        
        temp_path = CLIPS_DIR / f"_trim_temp_{clip_row['filename']}"
        cmd = ['ffmpeg', '-y', '-ss', str(start), '-i', str(src_path), '-t', str(end - start),
               '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k',
               str(temp_path)]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and temp_path.exists():
            src_path.unlink()
            temp_path.rename(src_path)
            new_dur = get_video_duration(src_path)
            if new_dur:
                db.execute("UPDATE clips SET duracion_s = ? WHERE id = ?", (new_dur, clip_id))
            thumb_path = THUMBS_DIR / (src_path.stem + '.jpg')
            generate_thumbnail(src_path, thumb_path)
            trim_count += 1
            log.info(f"  Trimmed: {clip_id} ({start}s - {end}s)")
        else:
            log.error(f"  Trim failed: {clip_id} - {result.stderr[:100]}")
            if temp_path.exists():
                temp_path.unlink()
    
    # 3. Aplicar audio swaps
    for clip_id, audio_filename in audio_assignments.items():
        clip_row = db.execute("SELECT filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip_row:
            continue
        
        video_path = CLIPS_DIR / clip_row['filename']
        audio_path = AUDIO_DIR / audio_filename
        if not video_path.exists() or not audio_path.exists():
            continue
        
        temp_path = CLIPS_DIR / f"_audio_temp_{clip_row['filename']}"
        cmd = ['ffmpeg', '-y', '-i', str(video_path), '-i', str(audio_path),
               '-c:v', 'copy', '-map', '0:v:0', '-map', '1:a:0', '-shortest',
               str(temp_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and temp_path.exists():
            video_path.unlink()
            temp_path.rename(video_path)
            audio_count += 1
            log.info(f"  Audio swapped: {clip_id} <- {audio_filename}")
        else:
            log.error(f"  Audio swap failed: {clip_id}")
            if temp_path.exists():
                temp_path.unlink()
    
    # 4. Guardar feedback
    for clip_id, note in feedback.items():
        if note.strip():
            db.execute("DELETE FROM user_feedback WHERE shortcode = ? AND step = 'clip_review'", (clip_id,))
            db.execute("""
                INSERT INTO user_feedback (shortcode, step, user_said, decision)
                VALUES (?, 'clip_review', ?, 'feedback')
            """, (clip_id, note))
    
    db.commit()
    
    log.info("")
    log.info("=" * 50)
    log.info("   CATALOGO CLIPS - APLICADO")
    log.info("=" * 50)
    log.info(f"   Aprobados:         {ok_count}")
    log.info(f"   Cambios aplicados: {changes_count}")
    log.info(f"   Rechazados:        {reject_count}")
    log.info(f"   Trims hechos:      {trim_count}")
    log.info(f"   Audio swaps:       {audio_count}")
    log.info("=" * 50)
    
    if changes_count > 0 or trim_count > 0 or audio_count > 0:
        log.info(f"")
        log.info(f"   {changes_count} clips con cambios quedan como PENDIENTES.")
        log.info(f"   Corre: python catalogo_clips.py --pendientes")
        log.info(f"   para revisar solo los que cambiaron.")
    
    if path.exists():
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description="Catalogo Visual de Clips")
    parser.add_argument('--apply', action='store_true', help="Aplicar decisiones del JSON")
    parser.add_argument('--pendientes', action='store_true', help="Solo clips sin aprobar")
    parser.add_argument('--ia', action='store_true', help="Solo clips categorizados por IA (muestra analisis completo)")
    parser.add_argument('--generar-thumbs', action='store_true', help="Regenerar thumbnails")
    parser.add_argument('--results-path', type=str, default=None)
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('catalogo_clips')
    log = get_logger()
    ensure_dirs()
    
    log.info("=== CATALOGO CLIPS - INICIO ===")
    
    if args.apply:
        apply_results(args.results_path)
        return
    
    if args.generar_thumbs:
        log.info("Regenerando thumbnails...")
        for f in CLIPS_DIR.glob('*.mp4'):
            thumb = THUMBS_DIR / (f.stem + '.jpg')
            generate_thumbnail(f, thumb)
            log.info(f"  {f.name}")
        log.info("Done.")
        return
    
    clips = get_all_clips(only_pending=args.pendientes, only_ia=args.ia)
    audios = get_available_audios()
    
    if not clips:
        log.info("No hay clips" + (" pendientes" if args.pendientes else "") + ". Descarga algunos con descargar_clips.py")
        return
    
    log.info(f"Clips: {len(clips)} | Audios: {len(audios)}")
    
    html = generate_html(clips, audios)
    CATALOG_HTML.write_text(html, encoding='utf-8')
    
    log.info(f"Servidor en http://127.0.0.1:{SERVER_PORT}")
    server = start_local_server()
    
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SERVER_PORT}/catalogo_clips.html"
    webbrowser.open(url)
    
    log.info("")
    log.info(f"   Catalogo abierto en el navegador")
    log.info(f"   Servidor: http://127.0.0.1:{SERVER_PORT}")
    log.info(f"   Clips: {len(clips)}")
    log.info("")
    log.info("   Controles:")
    log.info("     - Click en video = play/pause (CON AUDIO)")
    log.info("     - Timestamp visible durante reproduccion")
    log.info("     - ACTIVAR AUDIO = unmute todos los clips")
    log.info("     - APROBAR / CAMBIOS / RECHAZAR por clip")
    log.info("     - Trim: ajustar inicio/fin en segundos")
    log.info("     - Audio: seleccionar + Escuchar antes de asignar")
    log.info("     - YouTube link para re-descargar si necesitas")
    log.info("")
    log.info("   Presiona Ctrl+C para cerrar")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Cerrando...")
        server.shutdown()


if __name__ == "__main__":
    main()
