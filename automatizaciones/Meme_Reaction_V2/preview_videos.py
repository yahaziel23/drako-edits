#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Preview de Videos Generados

Interfaz para revisar videos generados antes de aprobar/subir.
Por cada video muestra:
  - Player del video generado (loop)
  - Imagen del meme original + clip original para comparar
  - Info: caption, score, clip mood
  - Controles para ajustar: caption text, caption size, trim
  - Acciones: APROBAR / REGENERAR / REGRESAR A MATCH / DESCARTAR

Uso:
    python preview_videos.py                   # Ver todos los generados
    python preview_videos.py --apply           # Aplicar decisiones del JSON
    python preview_videos.py --shortcode ABC   # Solo uno

Puerto: 8769
"""

import sys
import os
import json
import argparse
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

VIDEOS_DIR = SCRIPT_DIR / "videos"
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
CLIPS_DIR = SCRIPT_DIR / "clips"
PREVIEW_HTML = SCRIPT_DIR / "preview_videos.html"
SERVER_PORT = 8769


def get_generated_videos(shortcode=None):
    """Obtiene videos generados pendientes de aprobacion."""
    db = get_db()
    
    if shortcode:
        where = "WHERE m.shortcode = ?"
        params = (shortcode,)
    else:
        where = "WHERE m.status = 'generado'"
        params = ()
    
    rows = db.execute(f"""
        SELECT vg.id as video_id, vg.shortcode, vg.output_path, vg.config_json,
               vg.duracion_s, vg.variante_num,
               m.status as meme_status,
               mt.clip_id, mt.caption, mt.caption_size, mt.accuracy, mt.razon,
               cl.filename as clip_filename, cl.descripcion_corta as clip_desc, cl.mood as clip_mood,
               c.descripcion as meme_desc, c.categorias
        FROM videos_generados vg
        JOIN memes m ON vg.shortcode = m.shortcode
        JOIN matches mt ON vg.match_id = mt.id
        JOIN clips cl ON mt.clip_id = cl.id
        JOIN clasificaciones c ON vg.shortcode = c.shortcode
        {where}
        ORDER BY vg.generated_at DESC
    """, params).fetchall()
    
    results = []
    for row in rows:
        # Find meme image
        image_file = None
        for ext in ['.jpg', '.png', '.webp']:
            candidate = MEMES_DIR / (row['shortcode'] + ext)
            if candidate.exists():
                image_file = 'memes_descargados/' + row['shortcode'] + ext
                break
        
        # Video file relative path
        video_file = None
        output_path = Path(row['output_path'])
        if output_path.exists():
            video_file = 'videos/' + output_path.name
        
        # Clip file
        clip_file = 'clips/' + row['clip_filename'] if row['clip_filename'] else None
        
        # Parse config
        config = {}
        try:
            config = json.loads(row['config_json']) if row['config_json'] else {}
        except Exception:
            pass
        
        cats = []
        try:
            cats = json.loads(row['categorias']) if row['categorias'] else []
        except Exception:
            pass
        
        results.append({
            'video_id': row['video_id'],
            'shortcode': row['shortcode'],
            'video_file': video_file,
            'image_file': image_file,
            'clip_file': clip_file,
            'clip_id': row['clip_id'],
            'clip_desc': row['clip_desc'] or '',
            'clip_mood': row['clip_mood'] or '',
            'caption': row['caption'] or '',
            'caption_size': row['caption_size'] or 'M',
            'accuracy': row['accuracy'] or 0,
            'razon': row['razon'] or '',
            'duration': row['duracion_s'] or 0,
            'variant': row['variante_num'] or 1,
            'meme_desc': row['meme_desc'] or '',
            'categorias': cats,
            'config': config,
        })
    
    return results


def generate_html(videos_data):
    """Genera HTML del preview."""
    total = len(videos_data)
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>Preview Videos | ' + str(total) + ' generados</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,sans-serif;background:#0a0a12;color:#eee;padding:16px 24px}')
    html_parts.append('.hdr{text-align:center;margin-bottom:16px;padding:12px;background:linear-gradient(135deg,#12122a,#1a1a3a);border-radius:12px;border:1px solid #222}')
    html_parts.append('.hdr h1{font-size:1.2em}')
    html_parts.append('.hdr .sub{font-size:0.75em;color:#888;margin-top:4px}')
    html_parts.append('.tb{display:flex;justify-content:center;gap:8px;margin-bottom:16px}')
    html_parts.append('.tb button{padding:8px 16px;border:1px solid #333;background:#1a1a2e;color:#ddd;border-radius:8px;cursor:pointer;font-size:0.8em}')
    html_parts.append('.tb .sv{background:#00d4aa;color:#000;border-color:#00d4aa;font-weight:bold}')
    # Card
    html_parts.append('.vcard{background:#12122a;border-radius:12px;padding:16px;margin-bottom:16px;border:2px solid #1a1a2a;transition:all 0.3s}')
    html_parts.append('.vcard.approved{border-color:#4CAF50;opacity:0.7}')
    html_parts.append('.vcard.rejected{border-color:#f44336;opacity:0.5}')
    html_parts.append('.vcard-top{display:flex;gap:16px;margin-bottom:12px}')
    # Video player
    html_parts.append('.video-col{flex:1;max-width:400px}')
    html_parts.append('.video-col video{width:100%;max-height:500px;border-radius:8px;background:#000}')
    # Sources column
    html_parts.append('.sources-col{display:flex;flex-direction:column;gap:8px;flex:1}')
    html_parts.append('.source-label{font-size:0.65em;color:#666;text-transform:uppercase;letter-spacing:1px}')
    html_parts.append('.meme-thumb{width:100%;max-height:200px;object-fit:contain;border-radius:6px;background:#000}')
    html_parts.append('.clip-thumb{width:100%;max-height:120px;border-radius:6px;background:#000}')
    # Info column
    html_parts.append('.info-col{flex:1;display:flex;flex-direction:column;gap:6px}')
    html_parts.append('.info-row{display:flex;gap:8px;align-items:center}')
    html_parts.append('.label{font-size:0.65em;color:#666;min-width:60px}')
    html_parts.append('.value{font-size:0.75em;color:#ccc}')
    html_parts.append('.score-badge{padding:3px 8px;border-radius:8px;font-size:0.7em;font-weight:bold;background:#4CAF50;color:white}')
    html_parts.append('.mood-badge{padding:2px 6px;border-radius:8px;font-size:0.65em;background:#1a2a3a;color:#5bc0de}')
    html_parts.append('.tag{font-size:0.58em;padding:2px 5px;background:#1a2a3a;border-radius:6px;color:#5bc0de;display:inline-block;margin:1px}')
    html_parts.append('.desc{font-size:0.7em;color:#999;line-height:1.3}')
    # Controls
    html_parts.append('.controls{display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;padding:10px;background:#0a0a18;border-radius:8px;margin-bottom:10px}')
    html_parts.append('.ctrl-group{display:flex;flex-direction:column;gap:3px}')
    html_parts.append('.ctrl-group label{font-size:0.6em;color:#666;text-transform:uppercase}')
    html_parts.append('.ctrl-group input,.ctrl-group select{padding:5px 8px;border:1px solid #333;background:#12122a;color:#eee;border-radius:5px;font-size:0.75em}')
    html_parts.append('.ctrl-group input:focus,.ctrl-group select:focus{border-color:#00d4aa;outline:none}')
    # Action buttons
    html_parts.append('.actions{display:flex;gap:8px;flex-wrap:wrap}')
    html_parts.append('.btn{padding:8px 14px;border:none;border-radius:6px;cursor:pointer;font-size:0.75em;font-weight:bold;transition:all 0.15s}')
    html_parts.append('.btn-approve{background:#4CAF50;color:white}')
    html_parts.append('.btn-approve:hover{background:#45a049}')
    html_parts.append('.btn-regen{background:#2196F3;color:white}')
    html_parts.append('.btn-regen:hover{background:#1976D2}')
    html_parts.append('.btn-back{background:#ff9800;color:white}')
    html_parts.append('.btn-back:hover{background:#e68900}')
    html_parts.append('.btn-discard{background:#f44336;color:white}')
    html_parts.append('.btn-discard:hover{background:#d32f2f}')
    html_parts.append('#counter{position:fixed;bottom:16px;right:16px;background:#12122a;padding:10px 14px;border-radius:10px;font-size:0.75em;border:1px solid #222}')
    html_parts.append('</style></head><body>')
    
    # Header
    html_parts.append('<div class="hdr"><h1>Preview Videos Generados</h1>')
    html_parts.append('<div class="sub">' + str(total) + ' videos por revisar</div></div>')
    
    # Toolbar
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveDecisions()">&#128190; GUARDAR DECISIONES</button>')
    html_parts.append('<button onclick="approveAll()">&#9989; Aprobar todos</button>')
    html_parts.append('</div>')
    
    # Video cards
    for idx, v in enumerate(videos_data):
        vid = str(v['video_id'])
        sc = v['shortcode']
        
        video_tag = ''
        if v['video_file']:
            video_tag = '<video src="' + v['video_file'] + '" controls loop preload="metadata"></video>'
        else:
            video_tag = '<div style="padding:40px;text-align:center;color:#555">Video no encontrado</div>'
        
        img_tag = ''
        if v['image_file']:
            img_tag = '<img class="meme-thumb" src="' + v['image_file'] + '">'
        
        clip_tag = ''
        if v['clip_file']:
            clip_tag = '<video class="clip-thumb" src="' + v['clip_file'] + '" preload="metadata" onclick="this.paused?this.play():this.pause()" loop muted></video>'
        
        cats_html = ''.join(['<span class="tag">' + t + '</span>' for t in v['categorias'][:4]])
        
        html_parts.append('<div class="vcard" id="vc-' + vid + '" data-vid="' + vid + '" data-sc="' + sc + '">')
        html_parts.append('<div class="vcard-top">')
        
        # Video column
        html_parts.append('<div class="video-col">')
        html_parts.append('<div class="source-label">Video Generado (v' + str(v['variant']) + ')</div>')
        html_parts.append(video_tag)
        html_parts.append('</div>')
        
        # Sources column
        html_parts.append('<div class="sources-col">')
        html_parts.append('<div class="source-label">Meme Original</div>')
        html_parts.append(img_tag)
        html_parts.append('<div class="source-label">Clip Usado</div>')
        html_parts.append(clip_tag)
        html_parts.append('<div style="font-size:0.65em;color:#888">' + v['clip_desc'][:40] + '</div>')
        html_parts.append('</div>')
        
        # Info column
        html_parts.append('<div class="info-col">')
        html_parts.append('<div class="info-row"><span class="label">Score:</span><span class="score-badge">' + str(int(v['accuracy'])) + '%</span><span class="mood-badge">' + v['clip_mood'] + '</span></div>')
        html_parts.append('<div class="info-row"><span class="label">Caption:</span><span class="value">' + (v['caption'] if v['caption'] else '<em>sin caption</em>') + '</span></div>')
        html_parts.append('<div class="info-row"><span class="label">Size:</span><span class="value">' + v['caption_size'] + '</span></div>')
        html_parts.append('<div class="info-row"><span class="label">Duracion:</span><span class="value">' + f"{v['duration']:.1f}s" + '</span></div>')
        html_parts.append('<div class="info-row"><span class="label">Tags:</span><span>' + cats_html + '</span></div>')
        if v['razon']:
            html_parts.append('<div class="desc">' + v['razon'][:100] + '</div>')
        html_parts.append('</div>')
        html_parts.append('</div>')  # end vcard-top
        
        # Controls (edit before regen)
        cap_safe = v['caption'].replace('"', '&quot;')
        html_parts.append('<div class="controls">')
        html_parts.append('<div class="ctrl-group"><label>Caption</label><input type="text" id="cap-' + vid + '" value="' + cap_safe + '" placeholder="Sin caption" maxlength="50" style="width:220px"></div>')
        html_parts.append('<div class="ctrl-group"><label>Size</label><select id="size-' + vid + '"><option value="S"' + (' selected' if v['caption_size'] == 'S' else '') + '>S (42px)</option><option value="M"' + (' selected' if v['caption_size'] == 'M' else '') + '>M (58px)</option><option value="L"' + (' selected' if v['caption_size'] == 'L' else '') + '>L (76px)</option><option value="XL"' + (' selected' if v['caption_size'] == 'XL' else '') + '>XL (100px)</option></select></div>')
        html_parts.append('</div>')
        
        # Action buttons
        html_parts.append('<div class="actions">')
        html_parts.append('<button class="btn btn-approve" onclick="decide(\'' + vid + '\',\'approve\')">&#9989; APROBAR</button>')
        html_parts.append('<button class="btn btn-regen" onclick="decide(\'' + vid + '\',\'regenerate\')">&#128260; REGENERAR</button>')
        html_parts.append('<button class="btn btn-back" onclick="decide(\'' + vid + '\',\'back_to_match\')">&#8617; REGRESAR A MATCH</button>')
        html_parts.append('<button class="btn btn-discard" onclick="decide(\'' + vid + '\',\'discard\')">&#10060; DESCARTAR MEME</button>')
        html_parts.append('</div>')
        
        html_parts.append('</div>')  # end vcard
    
    # Counter
    html_parts.append('<div id="counter">Decididos: <b><span id="cnt">0</span> / ' + str(total) + '</b></div>')
    
    # JavaScript
    html_parts.append('<script>')
    html_parts.append('var decisions={};')
    html_parts.append('var total=' + str(total) + ';')
    html_parts.append('')
    html_parts.append('function decide(vid,action){')
    html_parts.append('  var card=document.getElementById("vc-"+vid);')
    html_parts.append('  var sc=card.dataset.sc;')
    html_parts.append('  var cap=document.getElementById("cap-"+vid).value;')
    html_parts.append('  var size=document.getElementById("size-"+vid).value;')
    html_parts.append('  decisions[vid]={action:action,shortcode:sc,caption:cap,caption_size:size};')
    html_parts.append('  card.className="vcard "+(action==="approve"?"approved":"rejected");')
    html_parts.append('  document.getElementById("cnt").textContent=Object.keys(decisions).length;')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function approveAll(){')
    html_parts.append('  document.querySelectorAll(".vcard").forEach(function(card){')
    html_parts.append('    var vid=card.dataset.vid;')
    html_parts.append('    if(!decisions[vid])decide(vid,"approve");')
    html_parts.append('  });')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function saveDecisions(){')
    html_parts.append('  var t=Object.keys(decisions).length;')
    html_parts.append('  if(t===0){alert("No has tomado ninguna decision.");return;}')
    html_parts.append('  var data={timestamp:new Date().toISOString(),total_decisions:t,decisions:decisions};')
    html_parts.append('  var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('  var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('  a.href=url;a.download="preview_results.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('  alert("Guardado: "+t+" decisiones.\\n\\nSiguiente:\\npython preview_videos.py --apply");')
    html_parts.append('}')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


def apply_results(results_path=None):
    """Aplica las decisiones del usuario."""
    log = get_logger()
    path = Path(results_path) if results_path else SCRIPT_DIR / "preview_results.json"
    downloads_path = Path.home() / "Downloads" / "preview_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
    else:
        log.error("No se encontro preview_results.json")
        return
    
    decisions = data.get('decisions', {})
    db = get_db()
    
    approved = 0
    regenerate = 0
    back_match = 0
    discarded = 0
    
    for vid, decision in decisions.items():
        action = decision.get('action', '')
        shortcode = decision.get('shortcode', '')
        caption = decision.get('caption', '')
        caption_size = decision.get('caption_size', 'M')
        
        if action == 'approve':
            db.execute("UPDATE memes SET status = 'por_subir' WHERE shortcode = ?", (shortcode,))
            db.execute("UPDATE videos_generados SET selected = 1 WHERE id = ?", (int(vid),))
            approved += 1
            
        elif action == 'regenerate':
            # Update caption in match, set meme back to por_generar
            db.execute("""
                UPDATE matches SET caption = ?, caption_size = ?
                WHERE shortcode = ? AND match_type = 'confirmed'
            """, (caption, caption_size, shortcode))
            db.execute("UPDATE memes SET status = 'por_generar' WHERE shortcode = ?", (shortcode,))
            # Mark old video as not selected
            db.execute("UPDATE videos_generados SET selected = 0 WHERE id = ?", (int(vid),))
            regenerate += 1
            
        elif action == 'back_to_match':
            # Unconfirm match, back to review
            db.execute("UPDATE matches SET match_type = 'auto' WHERE shortcode = ? AND match_type = 'confirmed'", (shortcode,))
            db.execute("UPDATE memes SET status = 'match_review' WHERE shortcode = ?", (shortcode,))
            back_match += 1
            
        elif action == 'discard':
            db.execute("UPDATE memes SET status = 'descartado_ia' WHERE shortcode = ?", (shortcode,))
            discarded += 1
        
        # Save feedback
        db.execute("""
            INSERT INTO user_feedback (shortcode, step, user_said, decision)
            VALUES (?, 'video_preview', ?, ?)
        """, (shortcode, json.dumps(decision, ensure_ascii=False), action))
    
    db.commit()
    
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   DECISIONES APLICADAS")
    log.info(f"{'='*55}")
    log.info(f"   Aprobados (por_subir):     {approved}")
    log.info(f"   Regenerar (nuevo caption): {regenerate}")
    log.info(f"   Regresar a match:          {back_match}")
    log.info(f"   Descartados:               {discarded}")
    log.info(f"{'='*55}")
    
    if approved > 0:
        log.info(f"   {approved} videos listos para subir.")
        log.info(f"   Siguiente: python 9_upload_social.py")
    if regenerate > 0:
        log.info(f"   {regenerate} videos para re-generar.")
        log.info(f"   Corre: python 7_generate_video.py")
    if back_match > 0:
        log.info(f"   {back_match} memes regresaron a matching.")
        log.info(f"   Corre: python catalogo_matches.py")
    
    if path.exists():
        path.unlink()


def start_local_server():
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="Preview de Videos Generados")
    parser.add_argument('--apply', action='store_true', help="Aplicar decisiones")
    parser.add_argument('--shortcode', type=str, default=None)
    parser.add_argument('--results-path', type=str, default=None)
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('preview_videos')
    log = get_logger()
    
    if args.apply:
        apply_results(args.results_path)
        return
    
    videos_data = get_generated_videos(shortcode=args.shortcode)
    
    if not videos_data:
        log.info("No hay videos generados pendientes de revision.")
        log.info("Genera primero: python 7_generate_video.py")
        return
    
    log.info(f"Generando preview para {len(videos_data)} videos...")
    
    html = generate_html(videos_data)
    PREVIEW_HTML.write_text(html, encoding='utf-8')
    
    server = start_local_server()
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SERVER_PORT}/preview_videos.html"
    webbrowser.open(url)
    
    log.info(f"")
    log.info(f"   Preview de videos abierto")
    log.info(f"   Videos: {len(videos_data)}")
    log.info(f"   Puerto: {SERVER_PORT}")
    log.info(f"")
    log.info(f"   Acciones por video:")
    log.info(f"     APROBAR    -> cola de subida (por_subir)")
    log.info(f"     REGENERAR  -> edita caption/size, regenera video")
    log.info(f"     REGRESAR   -> vuelve a elegir clip")
    log.info(f"     DESCARTAR  -> meme sale del pipeline")
    log.info(f"")
    log.info(f"   Presiona Ctrl+C para cerrar")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Cerrando...")
        server.shutdown()


if __name__ == "__main__":
    main()
