#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Catalogo Visual de Clips

Genera un HTML interactivo para ver, editar y aprobar clips de reaccion.
Muestra video preview, permite trim, cambiar audio, y aprobar/rechazar.

Requisitos:
    ffmpeg en PATH (para generar thumbnails y trim)

Uso:
    python catalogo_clips.py                    # Ver todos los clips
    python catalogo_clips.py --pendientes       # Solo clips sin aprobar
    python catalogo_clips.py --apply            # Aplicar decisiones del JSON
    python catalogo_clips.py --generar-thumbs   # Regenerar thumbnails

Acciones por clip:
    - APROBAR: Listo para match
    - RECHAZAR: No sirve, se descarta
    - TRIM: Ajustar inicio/fin (se aplica con ffmpeg)
    - AUDIO: Asignar audio de otro video
    - NOTAS: Feedback texto libre
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
    """Obtiene duracion con ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(filepath)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if result.returncode == 0 and result.stdout.strip():
        return float(result.stdout.strip())
    return None


def get_video_resolution(filepath):
    """Obtiene width x height con ffprobe."""
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


def get_all_clips():
    """Lee clips de la DB con metadata."""
    db = get_db()
    rows = db.execute("""
        SELECT id, descripcion, categorias, filename, duracion_s, usado_count, catalogado_at
        FROM clips
        ORDER BY catalogado_at DESC
    """).fetchall()
    
    clips = []
    for row in rows:
        clip_path = CLIPS_DIR / row['filename']
        if not clip_path.exists():
            continue
        
        thumb_path = THUMBS_DIR / (clip_path.stem + '.jpg')
        
        # Generar thumbnail si no existe
        if not thumb_path.exists():
            generate_thumbnail(clip_path, thumb_path)
        
        # Obtener resolucion si no la tenemos
        w, h = get_video_resolution(clip_path)
        
        cats = json.loads(row['categorias']) if row['categorias'] else []
        
        clips.append({
            'id': row['id'],
            'descripcion': row['descripcion'] or '',
            'categorias': cats,
            'filename': row['filename'],
            'duracion': row['duracion_s'] or 0,
            'usado_count': row['usado_count'] or 0,
            'catalogado_at': row['catalogado_at'] or '',
            'has_thumb': thumb_path.exists(),
            'width': w,
            'height': h,
            'orientation': 'horizontal' if (w and h and w > h) else 'vertical' if (w and h) else '?',
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
    """Genera HTML del catalogo visual."""
    
    cards = []
    for c in clips:
        cid = c['id']
        dur_str = f"{c['duracion']:.1f}s" if c['duracion'] else '?'
        orient_badge = '<span class="badge h">H</span>' if c['orientation'] == 'horizontal' else '<span class="badge v">V</span>' if c['orientation'] == 'vertical' else ''
        res_str = f"{c['width']}x{c['height']}" if c['width'] else '?'
        
        # Tags as pills
        tags_html = ''
        for tag in c['categorias']:
            tags_html += '<span class="tag">' + tag + '</span>'
        if not tags_html:
            tags_html = '<span class="tag empty">sin tags</span>'
        
        # Thumbnail o video preview
        thumb_src = f"clips/thumbs/{Path(c['filename']).stem}.jpg" if c['has_thumb'] else ''
        
        # Audio options
        audio_options = '<option value="">-- Audio original --</option>'
        for a in audios:
            audio_options += f'<option value="{a["filename"]}">{a["filename"]} ({a["duracion"]:.1f}s)</option>'
        
        desc_safe = c['descripcion'].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        
        card = (
            '<div class="card" id="c-' + cid + '" data-id="' + cid + '">'
            '<div class="card-top">'
            '<video class="preview" src="clips/' + c['filename'] + '" poster="' + thumb_src + '" preload="metadata" onclick="this.paused?this.play():this.pause()" loop muted></video>'
            '<div class="card-actions">'
            '<button class="btn-ok" onclick="markOk(\'' + cid + '\')">APROBAR</button>'
            '<button class="btn-no" onclick="markReject(\'' + cid + '\')">RECHAZAR</button>'
            '</div>'
            '<div class="dur">' + dur_str + '</div>'
            '</div>'
            '<div class="card-body">'
            '<div class="card-header">'
            '<span class="clip-id">' + cid[:20] + '</span>'
            + orient_badge +
            '<span class="res">' + res_str + '</span>'
            '</div>'
            '<div class="desc">' + desc_safe[:80] + '</div>'
            '<div class="tags">' + tags_html + '</div>'
            '<details><summary>Editar</summary>'
            '<div class="edit-section">'
            '<label>Trim (segundos):</label>'
            '<div class="trim-row">'
            '<input type="number" class="trim-start" data-id="' + cid + '" placeholder="inicio" step="0.5" min="0">'
            '<input type="number" class="trim-end" data-id="' + cid + '" placeholder="fin" step="0.5" max="' + str(c['duracion']) + '">'
            '</div>'
            '<label>Audio:</label>'
            '<select class="audio-select" data-id="' + cid + '">' + audio_options + '</select>'
            '</div>'
            '</details>'
            '<textarea class="notes" placeholder="Notas..." data-id="' + cid + '"></textarea>'
            '</div>'
            '</div>'
        )
        cards.append(card)
    
    cards_html = '\n'.join(cards)
    total = str(len(clips))
    
    # Stats
    horizontal = sum(1 for c in clips if c['orientation'] == 'horizontal')
    vertical = sum(1 for c in clips if c['orientation'] == 'vertical')
    avg_dur = sum(c['duracion'] for c in clips) / len(clips) if clips else 0
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>Catalogo Clips - ' + total + ' clips</title>')
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
    html_parts.append('.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:15px}')
    html_parts.append('.card{background:#1a1a2e;border-radius:10px;overflow:hidden;border:2px solid transparent;transition:all 0.2s}')
    html_parts.append('.card.marked-ok{border-color:#4CAF50;opacity:0.85}')
    html_parts.append('.card.marked-reject{border-color:#f44336;opacity:0.5}')
    html_parts.append('.card-top{position:relative}')
    html_parts.append('.preview{width:100%;height:200px;object-fit:contain;background:#000;display:block;cursor:pointer}')
    html_parts.append('.card-actions{position:absolute;bottom:5px;right:5px;display:flex;gap:4px}')
    html_parts.append('.card-actions button{padding:5px 10px;border:none;border-radius:5px;cursor:pointer;font-size:0.75em;font-weight:bold}')
    html_parts.append('.btn-ok{background:#4CAF50;color:white}')
    html_parts.append('.btn-no{background:#f44336;color:white}')
    html_parts.append('.dur{position:absolute;top:5px;right:5px;background:rgba(0,0,0,0.7);padding:2px 6px;border-radius:4px;font-size:0.75em}')
    html_parts.append('.card-body{padding:10px}')
    html_parts.append('.card-header{display:flex;align-items:center;gap:8px;margin-bottom:5px}')
    html_parts.append('.clip-id{font-family:monospace;font-size:0.7em;color:#aaa}')
    html_parts.append('.badge{font-size:0.65em;padding:2px 5px;border-radius:3px;font-weight:bold}')
    html_parts.append('.badge.h{background:#2196F3;color:white}')
    html_parts.append('.badge.v{background:#ff9800;color:white}')
    html_parts.append('.res{font-size:0.7em;color:#888}')
    html_parts.append('.desc{font-size:0.8em;color:#ccc;margin-bottom:5px;line-height:1.3}')
    html_parts.append('.tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px}')
    html_parts.append('.tag{font-size:0.65em;padding:2px 6px;background:#16213e;border-radius:10px;color:#00d4aa}')
    html_parts.append('.tag.empty{color:#666}')
    html_parts.append('details{margin-top:5px}')
    html_parts.append('summary{cursor:pointer;font-size:0.8em;color:#00d4aa}')
    html_parts.append('.edit-section{margin-top:8px;display:flex;flex-direction:column;gap:6px}')
    html_parts.append('.edit-section label{font-size:0.75em;color:#aaa}')
    html_parts.append('.trim-row{display:flex;gap:5px}')
    html_parts.append('.trim-row input{width:70px;padding:4px;border:1px solid #333;border-radius:4px;background:#0f0f1a;color:#eee;font-size:0.8em}')
    html_parts.append('.audio-select{padding:4px;border:1px solid #333;border-radius:4px;background:#0f0f1a;color:#eee;font-size:0.8em;width:100%}')
    html_parts.append('.notes{width:100%;height:40px;padding:5px;border:1px solid #333;border-radius:5px;background:#0a0a15;color:#eee;font-size:0.8em;resize:vertical;margin-top:5px}')
    html_parts.append('</style></head><body>')
    
    # Header
    html_parts.append('<div class="hdr">')
    html_parts.append('<h1>Catalogo de Clips de Reaccion</h1>')
    html_parts.append('<div class="stats">')
    html_parts.append('<span id="stotal">Total: ' + total + '</span>')
    html_parts.append('<span>Horizontal: ' + str(horizontal) + '</span>')
    html_parts.append('<span>Vertical: ' + str(vertical) + '</span>')
    html_parts.append('<span>Dur promedio: ' + f"{avg_dur:.1f}s" + '</span>')
    html_parts.append('<span>Audios: ' + str(len(audios)) + '</span>')
    html_parts.append('<span id="sok">Aprobados: 0</span>')
    html_parts.append('<span id="srj">Rechazados: 0</span>')
    html_parts.append('</div></div>')
    
    # Toolbar
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveResults()">GUARDAR DECISIONES</button>')
    html_parts.append('<button style="background:#555;color:#fff" onclick="playAll()">PLAY ALL (hover)</button>')
    html_parts.append('</div>')
    
    # Grid
    html_parts.append('<div class="grid">' + cards_html + '</div>')
    
    # JavaScript
    html_parts.append('<script>')
    html_parts.append('var D={};var notes={};var trims={};var audios_map={};')
    html_parts.append('function markOk(id){D[id]="ok";document.getElementById("c-"+id).className="card marked-ok";upd();}')
    html_parts.append('function markReject(id){D[id]="reject";document.getElementById("c-"+id).className="card marked-reject";upd();}')
    html_parts.append('function upd(){')
    html_parts.append('var ok=0,rj=0;for(var k in D){if(D[k]==="ok")ok++;if(D[k]==="reject")rj++;}')
    html_parts.append('document.getElementById("sok").textContent="Aprobados: "+ok;')
    html_parts.append('document.getElementById("srj").textContent="Rechazados: "+rj;}')
    html_parts.append('function playAll(){document.querySelectorAll(".preview").forEach(function(v){v.muted=true;v.addEventListener("mouseenter",function(){this.play()});v.addEventListener("mouseleave",function(){this.pause();this.currentTime=0});});}')
    html_parts.append('function saveResults(){')
    html_parts.append('document.querySelectorAll(".notes").forEach(function(ta){if(ta.value.trim())notes[ta.dataset.id]=ta.value.trim();});')
    html_parts.append('document.querySelectorAll(".trim-start").forEach(function(inp){if(inp.value){if(!trims[inp.dataset.id])trims[inp.dataset.id]={};trims[inp.dataset.id].start=parseFloat(inp.value);}});')
    html_parts.append('document.querySelectorAll(".trim-end").forEach(function(inp){if(inp.value){if(!trims[inp.dataset.id])trims[inp.dataset.id]={};trims[inp.dataset.id].end=parseFloat(inp.value);}});')
    html_parts.append('document.querySelectorAll(".audio-select").forEach(function(sel){if(sel.value)audios_map[sel.dataset.id]=sel.value;});')
    html_parts.append('var t=Object.keys(D).length;')
    html_parts.append('var data={timestamp:new Date().toISOString(),total_decisions:t,decisions:D,feedback:notes,trims:trims,audio_assignments:audios_map};')
    html_parts.append('var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('a.href=url;a.download="catalogo_results.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('alert("Guardado: "+t+" decisiones, "+Object.keys(trims).length+" trims, "+Object.keys(audios_map).length+" audios.\\n\\nCorre: python catalogo_clips.py --apply");}')
    html_parts.append('playAll();')
    html_parts.append('console.log("CatalogoClips OK: "+document.querySelectorAll(".card").length+" clips");')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


def start_local_server():
    """Inicia servidor HTTP local."""
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None  # Silenciar logs
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def apply_results(results_path=None):
    """Aplica decisiones: aprobar/rechazar, trim, audio."""
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
    reject_count = 0
    trim_count = 0
    audio_count = 0
    
    # Aplicar decisiones
    for clip_id, decision in decisions.items():
        if decision == 'ok':
            # Marcar como aprobado (categorias no vacias = aprobado)
            # Por ahora solo confirmamos que existe
            ok_count += 1
        elif decision == 'reject':
            # Borrar de la DB y mover archivo a clips/rejected/
            clip_row = db.execute("SELECT filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
            if clip_row:
                rejected_dir = CLIPS_DIR / "rejected"
                rejected_dir.mkdir(exist_ok=True)
                src = CLIPS_DIR / clip_row['filename']
                if src.exists():
                    src.rename(rejected_dir / clip_row['filename'])
                db.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            reject_count += 1
    
    # Aplicar trims con ffmpeg
    for clip_id, trim_data in trims.items():
        clip_row = db.execute("SELECT filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip_row:
            continue
        
        src_path = CLIPS_DIR / clip_row['filename']
        if not src_path.exists():
            continue
        
        start = trim_data.get('start', 0)
        end = trim_data.get('end')
        
        # Trim con ffmpeg (sobreescribir)
        temp_path = CLIPS_DIR / f"_trim_temp_{clip_row['filename']}"
        cmd = ['ffmpeg', '-y', '-ss', str(start)]
        cmd += ['-i', str(src_path)]
        if end:
            cmd += ['-t', str(end - start)]
        cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', str(temp_path)]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and temp_path.exists():
            src_path.unlink()
            temp_path.rename(src_path)
            # Actualizar duracion en DB
            new_dur = get_video_duration(src_path)
            if new_dur:
                db.execute("UPDATE clips SET duracion_s = ? WHERE id = ?", (new_dur, clip_id))
            # Regenerar thumbnail
            thumb_path = THUMBS_DIR / (src_path.stem + '.jpg')
            generate_thumbnail(src_path, thumb_path)
            trim_count += 1
            log.info(f"  Trimmed: {clip_id} ({start}s - {end}s)")
        else:
            log.error(f"  Trim failed: {clip_id}")
            if temp_path.exists():
                temp_path.unlink()
    
    # Aplicar audio swaps
    for clip_id, audio_filename in audio_assignments.items():
        clip_row = db.execute("SELECT filename FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if not clip_row:
            continue
        
        video_path = CLIPS_DIR / clip_row['filename']
        audio_path = AUDIO_DIR / audio_filename
        
        if not video_path.exists() or not audio_path.exists():
            continue
        
        # Reemplazar audio con ffmpeg
        temp_path = CLIPS_DIR / f"_audio_temp_{clip_row['filename']}"
        cmd = [
            'ffmpeg', '-y',
            '-i', str(video_path),
            '-i', str(audio_path),
            '-c:v', 'copy',
            '-map', '0:v:0', '-map', '1:a:0',
            '-shortest',
            str(temp_path)
        ]
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
    
    # Guardar feedback
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
    log.info(f"   Aprobados:     {ok_count}")
    log.info(f"   Rechazados:    {reject_count}")
    log.info(f"   Trimmed:       {trim_count}")
    log.info(f"   Audio swaps:   {audio_count}")
    log.info("=" * 50)
    
    if path.exists():
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description="Catalogo Visual de Clips")
    parser.add_argument('--apply', action='store_true', help="Aplicar decisiones del JSON")
    parser.add_argument('--pendientes', action='store_true', help="Solo clips sin categorias")
    parser.add_argument('--generar-thumbs', action='store_true', help="Regenerar todos los thumbnails")
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
            log.info(f"  {f.name} -> thumb")
        log.info("Done.")
        return
    
    # Obtener datos
    clips = get_all_clips()
    audios = get_available_audios()
    
    if not clips:
        log.info("No hay clips en la DB. Descarga algunos primero con descargar_clips.py")
        return
    
    log.info(f"Clips: {len(clips)} | Audios disponibles: {len(audios)}")
    
    # Generar HTML
    html = generate_html(clips, audios)
    CATALOG_HTML.write_text(html, encoding='utf-8')
    
    # Servir
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
    log.info("   Acciones:")
    log.info("     - Click en video para play/pause")
    log.info("     - Hover para auto-play (despues de PLAY ALL)")
    log.info("     - APROBAR / RECHAZAR por clip")
    log.info("     - Trim: poner inicio/fin en segundos")
    log.info("     - Audio: seleccionar otro audio del dropdown")
    log.info("     - GUARDAR DECISIONES cuando termines")
    log.info("")
    log.info("   Presiona Ctrl+C para cerrar el servidor")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Cerrando servidor...")
        server.shutdown()


if __name__ == "__main__":
    main()
