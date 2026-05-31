#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Catalogo de Matches (Interfaz de Decision)

Interfaz HTML meme-por-meme para decidir matches finales.
Por cada meme muestra:
  - Imagen del meme
  - Top 3 clips con video preview + compatibilidad + captions
  - Clips con baja compatibilidad (separados, marcados)
  - Sugerencias de YouTube si no hay buen match
  - Opcion de skip (pendiente)

Todas las decisiones se guardan en user_feedback para entrenamiento futuro.

Uso:
    python catalogo_matches.py                 # Ver todos los matches pendientes
    python catalogo_matches.py --apply         # Aplicar decisiones del JSON
    python catalogo_matches.py --export        # Exportar decisiones para analisis

Puerto: 8768
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

MEMES_DIR = SCRIPT_DIR / "memes"
CLIPS_DIR = SCRIPT_DIR / "clips"
MATCH_HTML = SCRIPT_DIR / "catalogo_matches.html"
MATCH_RESULTS = SCRIPT_DIR / "match_results.json"
SERVER_PORT = 8768


def get_matches_for_review():
    """Obtiene memes con matches listos para revision."""
    db = get_db()
    
    # Get memes in review states
    memes = db.execute("""
        SELECT m.shortcode, m.image_path, m.status,
               c.descripcion, c.categorias, c.ideas_video
        FROM memes m
        JOIN clasificaciones c ON m.shortcode = c.shortcode
        WHERE m.status IN ('match_review', 'buscar_clip', 'por_generar')
        ORDER BY 
            CASE m.status 
                WHEN 'match_review' THEN 1 
                WHEN 'por_generar' THEN 2
                WHEN 'buscar_clip' THEN 3 
            END
    """).fetchall()
    
    results = []
    for meme in memes:
        # Get matches for this meme
        matches = db.execute("""
            SELECT clip_id, accuracy, caption, match_rank, razon, 
                   captions_json, youtube_sugerencias
            FROM matches
            WHERE shortcode = ?
            ORDER BY match_rank ASC
        """, (meme['shortcode'],)).fetchall()
        
        # Parse categories
        cats = []
        try:
            cats = json.loads(meme['categorias']) if meme['categorias'] else []
        except Exception:
            pass
        
        # Find meme image
        image_file = None
        for ext in ['.jpg', '.png', '.webp']:
            candidate = MEMES_DIR / (meme['shortcode'] + ext)
            if candidate.exists():
                image_file = 'memes/' + meme['shortcode'] + ext
                break
        
        # Parse matches
        match_list = []
        youtube_sugs = []
        for m in matches:
            captions = []
            try:
                captions = json.loads(m['captions_json']) if m['captions_json'] else []
            except Exception:
                if m['caption']:
                    captions = [m['caption']]
            
            if m['youtube_sugerencias']:
                try:
                    youtube_sugs = json.loads(m['youtube_sugerencias'])
                except Exception:
                    pass
            
            # Get clip info
            clip_file = None
            clip_row = db.execute("SELECT filename, descripcion_corta, mood FROM clips WHERE id = ?", 
                                  (m['clip_id'],)).fetchone()
            if clip_row:
                clip_file = 'clips/' + clip_row['filename']
            
            match_list.append({
                'clip_id': m['clip_id'],
                'score': m['accuracy'],
                'razon': m['razon'] or '',
                'captions': captions,
                'clip_file': clip_file,
                'clip_desc': clip_row['descripcion_corta'] if clip_row else '',
                'clip_mood': clip_row['mood'] if clip_row else '',
            })
        
        results.append({
            'shortcode': meme['shortcode'],
            'image_file': image_file,
            'status': meme['status'],
            'descripcion': meme['descripcion'] or '',
            'categorias': cats,
            'matches': match_list,
            'youtube_sugs': youtube_sugs,
        })
    
    return results


def generate_html(memes_data):
    """Genera HTML completo del catalogo de matches."""
    
    # Build meme cards
    meme_cards = []
    for idx, meme in enumerate(memes_data):
        sc = meme['shortcode']
        cats_html = ' '.join(['<span class="tag">' + t + '</span>' for t in meme['categorias'][:5]])
        status_class = 'status-' + meme['status'].replace('_', '-')
        
        # Match options HTML
        options_html = ''
        for mi, m in enumerate(meme['matches']):
            score = m['score']
            score_class = 'score-high' if score >= 90 else 'score-mid' if score >= 40 else 'score-low'
            captions_btns = ''
            for ci, cap in enumerate(m['captions']):
                cap_safe = cap.replace("'", "\\'")
                captions_btns += '<button class="cap-btn" onclick="pickCaption(\'' + sc + '\',\'' + m['clip_id'] + '\',\'' + cap_safe + '\')">' + cap + '</button>'
            captions_btns += '<button class="cap-btn cap-none" onclick="pickCaption(\'' + sc + '\',\'' + m['clip_id'] + '\',\'\')">Sin caption</button>'
            
            video_tag = ''
            if m['clip_file']:
                video_tag = '<video class="clip-preview" src="' + m['clip_file'] + '" preload="metadata" onclick="this.paused?this.play():this.pause()" loop></video>'
            
            options_html += (
                '<div class="match-option" data-sc="' + sc + '" data-clip="' + m['clip_id'] + '">'
                '<div class="opt-header">'
                '<span class="score ' + score_class + '">' + str(score) + '%</span>'
                '<span class="clip-mood">' + m['clip_mood'] + '</span>'
                '<span class="clip-desc">' + m['clip_desc'][:40] + '</span>'
                '</div>'
                + video_tag +
                '<div class="opt-razon">' + m['razon'][:100] + '</div>'
                '<div class="captions-row">' + captions_btns + '</div>'
                '<button class="btn-select" onclick="selectMatch(\'' + sc + '\',\'' + m['clip_id'] + '\')">ELEGIR ESTE</button>'
                '</div>'
            )
        
        # YouTube suggestions
        yt_html = ''
        if meme['youtube_sugs']:
            yt_items = ''.join(['<li><a href="https://www.youtube.com/results?search_query=' + s.replace(' ', '+') + '" target="_blank">' + s + '</a></li>' for s in meme['youtube_sugs']])
            yt_html = '<div class="yt-section"><b>Buscar clips en YouTube:</b><ul>' + yt_items + '</ul></div>'
        
        # Image
        img_html = ''
        if meme['image_file']:
            img_html = '<img class="meme-img" src="' + meme['image_file'] + '" onclick="zoomImg(this.src)">'
        
        card = (
            '<div class="meme-card" id="mc-' + sc + '" data-sc="' + sc + '">'
            '<div class="meme-left">'
            + img_html +
            '<div class="meme-info">'
            '<span class="sc">' + sc + '</span>'
            '<span class="' + status_class + '">' + meme['status'] + '</span>'
            '</div>'
            '<div class="meme-cats">' + cats_html + '</div>'
            '<div class="meme-desc">' + meme['descripcion'][:120] + '</div>'
            '<div class="meme-actions">'
            '<button class="btn-skip" onclick="skipMeme(\'' + sc + '\')">SKIP (pendiente)</button>'
            '</div>'
            '</div>'
            '<div class="meme-right">'
            '<div class="matches-title">Clips sugeridos (' + str(len(meme['matches'])) + ')</div>'
            '<div class="matches-grid">' + options_html + '</div>'
            + yt_html +
            '</div>'
            '</div>'
        )
        meme_cards.append(card)
    
    cards_html = '\n'.join(meme_cards)
    total = len(memes_data)
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>Match Meme-Clip - ' + str(total) + ' memes</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,sans-serif;background:#0a0a12;color:#eee;padding:20px}')
    html_parts.append('.hdr{text-align:center;margin-bottom:20px;padding:15px;background:#12122a;border-radius:10px}')
    html_parts.append('.hdr h1{font-size:1.3em;margin-bottom:5px}')
    html_parts.append('.stats{font-size:0.8em;color:#888}')
    html_parts.append('.tb{display:flex;justify-content:center;gap:10px;margin-bottom:20px}')
    html_parts.append('.tb button{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-weight:bold}')
    html_parts.append('.sv{background:#00d4aa;color:#000}')
    html_parts.append('.meme-card{display:flex;gap:15px;background:#12122a;border-radius:12px;padding:15px;margin-bottom:15px;border:2px solid transparent;transition:all 0.3s}')
    html_parts.append('.meme-card.decided{border-color:#4CAF50;opacity:0.7}')
    html_parts.append('.meme-card.skipped{border-color:#ff9800;opacity:0.5}')
    html_parts.append('.meme-left{width:280px;min-width:280px;display:flex;flex-direction:column;gap:8px}')
    html_parts.append('.meme-img{width:100%;max-height:300px;object-fit:contain;border-radius:8px;cursor:pointer;background:#000}')
    html_parts.append('.meme-info{display:flex;gap:8px;align-items:center}')
    html_parts.append('.sc{font-family:monospace;font-size:0.7em;color:#666}')
    html_parts.append('.meme-cats{display:flex;flex-wrap:wrap;gap:3px}')
    html_parts.append('.tag{font-size:0.6em;padding:2px 5px;background:#1a2a3a;border-radius:8px;color:#00d4aa}')
    html_parts.append('.meme-desc{font-size:0.75em;color:#aaa;line-height:1.3}')
    html_parts.append('.meme-actions{margin-top:auto}')
    html_parts.append('.btn-skip{width:100%;padding:8px;border:1px solid #ff9800;background:transparent;color:#ff9800;border-radius:6px;cursor:pointer;font-size:0.8em}')
    html_parts.append('.meme-right{flex:1;display:flex;flex-direction:column;gap:8px}')
    html_parts.append('.matches-title{font-size:0.85em;font-weight:bold;color:#00d4aa}')
    html_parts.append('.matches-grid{display:flex;flex-direction:column;gap:10px}')
    html_parts.append('.match-option{background:#0a0a18;border:1px solid #222;border-radius:8px;padding:10px;transition:all 0.2s}')
    html_parts.append('.match-option.selected{border-color:#4CAF50;background:#0a1a0a}')
    html_parts.append('.opt-header{display:flex;gap:8px;align-items:center;margin-bottom:6px}')
    html_parts.append('.score{padding:3px 8px;border-radius:10px;font-size:0.75em;font-weight:bold}')
    html_parts.append('.score-high{background:#4CAF50;color:white}')
    html_parts.append('.score-mid{background:#ff9800;color:white}')
    html_parts.append('.score-low{background:#f44336;color:white}')
    html_parts.append('.clip-mood{font-size:0.7em;color:#888}')
    html_parts.append('.clip-desc{font-size:0.7em;color:#aaa}')
    html_parts.append('.clip-preview{width:100%;max-height:150px;object-fit:contain;background:#000;border-radius:6px;cursor:pointer}')
    html_parts.append('.opt-razon{font-size:0.7em;color:#777;margin:4px 0;font-style:italic}')
    html_parts.append('.captions-row{display:flex;flex-wrap:wrap;gap:4px;margin:5px 0}')
    html_parts.append('.cap-btn{padding:4px 8px;border:1px solid #333;background:#1a1a2e;color:#ddd;border-radius:15px;cursor:pointer;font-size:0.7em;transition:all 0.15s}')
    html_parts.append('.cap-btn:hover{border-color:#00d4aa}')
    html_parts.append('.cap-btn.picked{background:#00d4aa;color:#000;border-color:#00d4aa}')
    html_parts.append('.cap-none{color:#888;font-style:italic}')
    html_parts.append('.btn-select{width:100%;padding:6px;border:none;background:#2196F3;color:white;border-radius:5px;cursor:pointer;font-size:0.75em;font-weight:bold;margin-top:5px}')
    html_parts.append('.btn-select:hover{background:#1976D2}')
    html_parts.append('.yt-section{margin-top:8px;padding:8px;background:#1a1a0a;border-radius:6px;border:1px solid #333}')
    html_parts.append('.yt-section b{font-size:0.8em;color:#ff9800}')
    html_parts.append('.yt-section ul{margin:5px 0 0 15px;font-size:0.75em}')
    html_parts.append('.yt-section a{color:#2196F3}')
    html_parts.append('.status-match-review{font-size:0.65em;padding:2px 6px;background:#ff9800;border-radius:8px;color:white}')
    html_parts.append('.status-por-generar{font-size:0.65em;padding:2px 6px;background:#4CAF50;border-radius:8px;color:white}')
    html_parts.append('.status-buscar-clip{font-size:0.65em;padding:2px 6px;background:#f44336;border-radius:8px;color:white}')
    html_parts.append('#zoom-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);display:none;align-items:center;justify-content:center;z-index:200;cursor:pointer}')
    html_parts.append('#zoom-overlay img{max-width:90%;max-height:90%;object-fit:contain}')
    html_parts.append('#counter{position:fixed;bottom:20px;right:20px;background:#12122a;padding:10px 15px;border-radius:8px;font-size:0.8em;border:1px solid #333}')
    html_parts.append('</style></head><body>')
    
    # Header
    html_parts.append('<div class="hdr"><h1>Match Meme - Clip</h1>')
    html_parts.append('<div class="stats">Memes: ' + str(total) + ' | Decide clip + caption por cada uno</div></div>')
    
    # Toolbar
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveDecisions()">GUARDAR DECISIONES</button>')
    html_parts.append('</div>')
    
    # Cards
    html_parts.append(cards_html)
    
    # Zoom overlay
    html_parts.append('<div id="zoom-overlay" onclick="this.style.display=\'none\'"><img id="zoom-img"></div>')
    
    # Counter
    html_parts.append('<div id="counter">Decididos: <span id="cnt">0</span> / ' + str(total) + '</div>')
    
    # JavaScript
    html_parts.append('<script>')
    html_parts.append('var decisions={};')
    html_parts.append('function selectMatch(sc,clipId){if(!decisions[sc])decisions[sc]={};decisions[sc].clip_id=clipId;decisions[sc].action="match";document.querySelectorAll("#mc-"+sc+" .match-option").forEach(function(o){o.classList.remove("selected");if(o.dataset.clip===clipId)o.classList.add("selected");});document.getElementById("mc-"+sc).classList.add("decided");document.getElementById("mc-"+sc).classList.remove("skipped");updCnt();}')
    html_parts.append('function pickCaption(sc,clipId,cap){if(!decisions[sc])decisions[sc]={};decisions[sc].clip_id=clipId;decisions[sc].caption=cap;decisions[sc].action="match";var card=document.getElementById("mc-"+sc);card.querySelectorAll(".match-option").forEach(function(o){o.classList.remove("selected");if(o.dataset.clip===clipId)o.classList.add("selected");});card.querySelectorAll(".cap-btn").forEach(function(b){b.classList.remove("picked");});event.target.classList.add("picked");card.classList.add("decided");card.classList.remove("skipped");updCnt();}')
    html_parts.append('function skipMeme(sc){decisions[sc]={action:"skip"};document.getElementById("mc-"+sc).classList.add("skipped");document.getElementById("mc-"+sc).classList.remove("decided");updCnt();}')
    html_parts.append('function zoomImg(src){document.getElementById("zoom-img").src=src;document.getElementById("zoom-overlay").style.display="flex";}')
    html_parts.append('function updCnt(){document.getElementById("cnt").textContent=Object.keys(decisions).length;}')
    html_parts.append('function saveDecisions(){var t=Object.keys(decisions).length;if(t===0){alert("No has tomado ninguna decision.");return;}')
    html_parts.append('var data={timestamp:new Date().toISOString(),total_decisions:t,decisions:decisions};')
    html_parts.append('var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('a.href=url;a.download="match_results.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('alert("Guardado: "+t+" decisiones.\\n\\nCorre: python catalogo_matches.py --apply");}')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


def apply_results(results_path=None):
    """Aplica las decisiones del usuario."""
    log = get_logger()
    path = Path(results_path) if results_path else MATCH_RESULTS
    downloads_path = Path.home() / "Downloads" / "match_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
    else:
        log.error("No se encontro match_results.json")
        return
    
    decisions = data.get('decisions', {})
    db = get_db()
    
    matched = 0
    skipped = 0
    
    for shortcode, decision in decisions.items():
        action = decision.get('action', '')
        
        if action == 'match':
            clip_id = decision.get('clip_id', '')
            caption = decision.get('caption', '')
            
            # Update match as confirmed
            db.execute("""
                UPDATE matches SET match_type = 'confirmed'
                WHERE shortcode = ? AND clip_id = ?
            """, (shortcode, clip_id))
            
            # Update meme status
            db.execute("UPDATE memes SET status = 'por_generar' WHERE shortcode = ?", (shortcode,))
            
            # Save to user_feedback for learning
            db.execute("DELETE FROM user_feedback WHERE shortcode = ? AND step = 'match_decision'", (shortcode,))
            db.execute("""
                INSERT INTO user_feedback (shortcode, step, user_said, decision)
                VALUES (?, 'match_decision', ?, ?)
            """, (
                shortcode,
                json.dumps({'clip_id': clip_id, 'caption': caption}, ensure_ascii=False),
                'confirmed'
            ))
            
            matched += 1
            
        elif action == 'skip':
            db.execute("UPDATE memes SET status = 'pendiente_match' WHERE shortcode = ?", (shortcode,))
            
            db.execute("DELETE FROM user_feedback WHERE shortcode = ? AND step = 'match_decision'", (shortcode,))
            db.execute("""
                INSERT INTO user_feedback (shortcode, step, user_said, decision)
                VALUES (?, 'match_decision', 'skipped - no clip suitable', 'skip')
            """, (shortcode,))
            
            skipped += 1
    
    db.commit()
    
    log.info(f"")
    log.info(f"{'='*50}")
    log.info(f"   MATCHES APLICADOS")
    log.info(f"{'='*50}")
    log.info(f"   Confirmados: {matched}")
    log.info(f"   Skipped:     {skipped}")
    log.info(f"{'='*50}")
    
    if matched > 0:
        log.info(f"   {matched} memes listos para generar video.")
        log.info(f"   Siguiente: python 7_generate_video.py")
    
    if path.exists():
        path.unlink()


def export_decisions():
    """Exporta todas las decisiones para analisis futuro."""
    log = get_logger()
    db = get_db()
    
    rows = db.execute("""
        SELECT uf.shortcode, uf.step, uf.user_said, uf.decision, uf.created_at,
               c.categorias, c.descripcion,
               m.accuracy as match_score
        FROM user_feedback uf
        LEFT JOIN clasificaciones c ON uf.shortcode = c.shortcode
        LEFT JOIN matches m ON uf.shortcode = m.shortcode AND m.match_type = 'confirmed'
        WHERE uf.step = 'match_decision'
        ORDER BY uf.created_at DESC
    """).fetchall()
    
    export_data = {
        'exported_at': datetime.now().isoformat(),
        'total_decisions': len(rows),
        'decisions': []
    }
    
    for row in rows:
        user_said = {}
        try:
            user_said = json.loads(row['user_said']) if row['user_said'] else {}
        except Exception:
            user_said = {'raw': row['user_said']}
        
        export_data['decisions'].append({
            'shortcode': row['shortcode'],
            'action': row['decision'],
            'user_choice': user_said,
            'meme_categorias': row['categorias'],
            'meme_descripcion': row['descripcion'],
            'match_score': row['match_score'],
            'timestamp': row['created_at'],
        })
    
    export_path = SCRIPT_DIR / f"match_decisions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    export_path.write_text(json.dumps(export_data, indent=2, ensure_ascii=False), encoding='utf-8')
    
    log.info(f"Exportado: {export_path.name}")
    log.info(f"Total decisiones: {len(rows)}")
    log.info(f"Pasame este archivo para analizar tus preferencias.")


def start_local_server():
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="Catalogo de Matches - Interfaz de Decision")
    parser.add_argument('--apply', action='store_true', help="Aplicar decisiones del JSON")
    parser.add_argument('--export', action='store_true', help="Exportar decisiones para analisis")
    parser.add_argument('--results-path', type=str, default=None)
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('catalogo_matches')
    log = get_logger()
    
    if args.apply:
        apply_results(args.results_path)
        return
    
    if args.export:
        export_decisions()
        return
    
    # Generate HTML
    memes_data = get_matches_for_review()
    
    if not memes_data:
        log.info("No hay matches pendientes de revision.")
        log.info("Corre primero: python 4_match_clip.py")
        return
    
    log.info(f"Generando interfaz para {len(memes_data)} memes...")
    
    html = generate_html(memes_data)
    MATCH_HTML.write_text(html, encoding='utf-8')
    
    log.info(f"Servidor en http://127.0.0.1:{SERVER_PORT}")
    server = start_local_server()
    
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SERVER_PORT}/catalogo_matches.html"
    webbrowser.open(url)
    
    log.info(f"")
    log.info(f"   Catalogo de matches abierto")
    log.info(f"   Memes: {len(memes_data)}")
    log.info(f"")
    log.info(f"   Flujo:")
    log.info(f"     1. Por cada meme, click en un clip o caption")
    log.info(f"     2. O click SKIP si ninguno convence")
    log.info(f"     3. GUARDAR DECISIONES cuando termines")
    log.info(f"     4. python catalogo_matches.py --apply")
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
