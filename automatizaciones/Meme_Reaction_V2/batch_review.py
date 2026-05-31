#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Batch Review (Grid Visual HTML)

Genera una pagina HTML con grid de thumbnails para aprobar/rechazar
memes rapidamente.

Flujo:
1. python batch_review.py           -> genera HTML + abre en navegador (servidor local)
2. Aprueba/rechaza en el browser
3. Click 'GUARDAR' -> descarga review_results.json
4. Ctrl+C en terminal
5. python batch_review.py --apply   -> lee JSON, actualiza SQLite

Uso:
    python batch_review.py                    # Solo pendiente_review (frames)
    python batch_review.py --all              # Todo sin clasificar
    python batch_review.py --apply            # Lee JSON y aplica
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

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db, update_meme_status
from utils.config import load_config
from utils.logger import setup_logger, get_logger

MEMES_DIR = SCRIPT_DIR / "memes_descargados"
REVIEW_HTML = SCRIPT_DIR / "review_page.html"
REVIEW_RESULTS = SCRIPT_DIR / "review_results.json"
SERVER_PORT = 8765


def get_pending_memes(status_filter='pendiente_review', show_all=False):
    db = get_db()
    if show_all:
        rows = db.execute(
            "SELECT * FROM memes WHERE status IN ('pendiente_review', 'listo_clasificar') ORDER BY likes DESC"
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM memes WHERE status = ? ORDER BY likes DESC",
            (status_filter,)
        ).fetchall()
    memes = []
    for row in rows:
        shortcode = row['shortcode']
        img_path = MEMES_DIR / f"{shortcode}.jpg"
        if not img_path.exists():
            continue
        memes.append({
            'shortcode': shortcode,
            'source_profile': row['source_profile'] or '?',
            'source_type': row['source_type'] or '?',
            'likes': row['likes'] or 0,
            'comments': row['comments'] or 0,
        })
    return memes


def generate_html(memes):
    # Build cards with inline onclick (simplest possible JS)
    cards = []
    for m in memes:
        sc = m['shortcode']
        likes_str = f"{m['likes']:,}" if m['likes'] else '?'
        card = (
            '<div class="card" id="c-' + sc + '">'
            '<img src="memes_descargados/' + sc + '.jpg" onclick="zoomIn(this.src)">'
            '<div class="info">'
            '<span class="sc">' + sc[:11] + '</span>'
            '<span class="mt">' + m['source_type'] + ' | ' + likes_str + ' likes | @' + m['source_profile'] + '</span>'
            '</div>'
            '<div class="btns">'
            '<button class="ba" onclick="ap(\'' + sc + '\')">SI</button>'
            '<button class="br" onclick="rj(\'' + sc + '\')">NO</button>'
            '</div>'
            '</div>'
        )
        cards.append(card)
    
    cards_html = '\n'.join(cards)
    total = str(len(memes))
    
    # Build full HTML (no f-strings, no braces conflicts)
    html_parts = []
    html_parts.append('<!DOCTYPE html>')
    html_parts.append('<html><head><meta charset="UTF-8">')
    html_parts.append('<title>Batch Review - ' + total + ' memes</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#eee;padding:20px}')
    html_parts.append('.hdr{text-align:center;margin-bottom:20px;padding:15px;background:#16213e;border-radius:10px}')
    html_parts.append('.hdr h1{font-size:1.4em;margin-bottom:8px}')
    html_parts.append('.stats{display:flex;justify-content:center;gap:15px;font-size:0.9em}')
    html_parts.append('.stats span{padding:4px 12px;border-radius:15px;background:#0f3460}')
    html_parts.append('.tb{display:flex;justify-content:center;gap:10px;margin-bottom:20px;flex-wrap:wrap}')
    html_parts.append('.tb button{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:0.95em;font-weight:bold}')
    html_parts.append('.sv{background:#00d4aa;color:#000}')
    html_parts.append('.aa{background:#4CAF50;color:white}')
    html_parts.append('.ra{background:#f44336;color:white}')
    html_parts.append('.rs{background:#666;color:white}')
    html_parts.append('.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}')
    html_parts.append('.card{background:#16213e;border-radius:8px;overflow:hidden;border:3px solid transparent;transition:all 0.2s}')
    html_parts.append('.card.approved{border-color:#4CAF50;opacity:0.7}')
    html_parts.append('.card.rejected{border-color:#f44336;opacity:0.4}')
    html_parts.append('.card img{width:100%;height:180px;object-fit:cover;display:block;cursor:pointer}')
    html_parts.append('.info{padding:6px 8px}')
    html_parts.append('.sc{font-size:0.7em;color:#aaa;font-family:monospace;display:block}')
    html_parts.append('.mt{font-size:0.65em;color:#777}')
    html_parts.append('.btns{display:flex}')
    html_parts.append('.btns button{flex:1;padding:12px;border:none;cursor:pointer;font-size:1.1em;font-weight:bold}')
    html_parts.append('.ba{background:#1b4332;color:#4CAF50}')
    html_parts.append('.ba:hover{background:#2d6a4f}')
    html_parts.append('.br{background:#3d0000;color:#f44336}')
    html_parts.append('.br:hover{background:#660000}')
    html_parts.append('.zo{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.92);z-index:1000;justify-content:center;align-items:center;cursor:pointer}')
    html_parts.append('.zo.active{display:flex}')
    html_parts.append('.zo img{max-width:90vw;max-height:90vh;object-fit:contain}')
    html_parts.append('</style></head><body>')
    html_parts.append('<div class="hdr"><h1>Batch Review - Meme Reaction V2</h1>')
    html_parts.append('<div class="stats"><span>Total: ' + total + '</span>')
    html_parts.append('<span id="sa">Aprobados: 0</span>')
    html_parts.append('<span id="sr">Rechazados: 0</span>')
    html_parts.append('<span id="sp">Pendientes: ' + total + '</span></div></div>')
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="aa" onclick="approveAll()">Aprobar Todos</button>')
    html_parts.append('<button class="ra" onclick="rejectAll()">Rechazar Todos</button>')
    html_parts.append('<button class="rs" onclick="resetAll()">Reset</button>')
    html_parts.append('<button class="sv" onclick="saveResults()">GUARDAR DECISIONES</button>')
    html_parts.append('</div>')
    html_parts.append('<div class="grid">')
    html_parts.append(cards_html)
    html_parts.append('</div>')
    html_parts.append('<div class="zo" id="zo" onclick="this.classList.remove(\'active\')">')
    html_parts.append('<img id="zi" src=""></div>')
    html_parts.append('<script>')
    html_parts.append('var D={};')
    html_parts.append('function ap(sc){D[sc]="approved";document.getElementById("c-"+sc).className="card approved";upd();}')
    html_parts.append('function rj(sc){D[sc]="rejected";document.getElementById("c-"+sc).className="card rejected";upd();}')
    html_parts.append('function zoomIn(src){document.getElementById("zi").src=src;document.getElementById("zo").classList.add("active");}')
    html_parts.append('function upd(){')
    html_parts.append('var a=0,r=0;for(var k in D){if(D[k]==="approved")a++;if(D[k]==="rejected")r++;}')
    html_parts.append('var t=document.querySelectorAll(".card").length;')
    html_parts.append('document.getElementById("sa").textContent="Aprobados: "+a;')
    html_parts.append('document.getElementById("sr").textContent="Rechazados: "+r;')
    html_parts.append('document.getElementById("sp").textContent="Pendientes: "+(t-a-r);}')
    html_parts.append('function approveAll(){document.querySelectorAll(".card").forEach(function(c){var sc=c.id.slice(2);if(!D[sc])ap(sc);});}')
    html_parts.append('function rejectAll(){document.querySelectorAll(".card").forEach(function(c){var sc=c.id.slice(2);if(!D[sc])rj(sc);});}')
    html_parts.append('function resetAll(){D={};document.querySelectorAll(".card").forEach(function(c){c.className="card";});upd();}')
    html_parts.append('function saveResults(){')
    html_parts.append('var t=Object.keys(D).length;if(t===0){alert("No has tomado ninguna decision.");return;}')
    html_parts.append('var data={timestamp:new Date().toISOString(),total_decisions:t,decisions:D};')
    html_parts.append('var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('a.href=url;a.download="review_results.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('alert("Guardado: "+t+" decisiones.\\n\\nAhora corre:\\n  python batch_review.py --apply");}')
    html_parts.append('console.log("BatchReview OK: "+document.querySelectorAll(".card").length+" cards");')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


def start_local_server():
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a: None
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def apply_results(results_path=None):
    log = get_logger()
    path = Path(results_path) if results_path else REVIEW_RESULTS
    downloads_path = Path.home() / "Downloads" / "review_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
        log.info(f"Encontrado en Downloads: {path}")
    else:
        log.error("No se encontro review_results.json")
        log.error(f"  Buscado en: {REVIEW_RESULTS}")
        log.error(f"  Buscado en: {downloads_path}")
        return
    
    decisions = data.get('decisions', {})
    if not decisions:
        log.warning("El JSON no tiene decisiones.")
        return
    
    approved = 0
    rejected = 0
    for shortcode, decision in decisions.items():
        if decision == 'approved':
            update_meme_status(shortcode, 'listo_clasificar')
            approved += 1
        elif decision == 'rejected':
            update_meme_status(shortcode, 'rechazado')
            rejected += 1
    
    log.info("")
    log.info("=" * 50)
    log.info("   BATCH REVIEW APLICADO")
    log.info("=" * 50)
    log.info(f"   Aprobados (-> listo_clasificar): {approved}")
    log.info(f"   Rechazados (-> rechazado):       {rejected}")
    log.info(f"   Total decisiones:                {len(decisions)}")
    log.info("=" * 50)
    
    if path.exists():
        path.unlink()
        log.info(f"   JSON limpiado: {path.name}")


def main():
    parser = argparse.ArgumentParser(description="Batch Review")
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--status', type=str, default='pendiente_review')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--results-path', type=str, default=None)
    args = parser.parse_args()

    setup_logger('batch_review')
    log = get_logger()
    load_config()
    init_db()

    if args.apply:
        apply_results(args.results_path)
        return

    memes = get_pending_memes(status_filter=args.status, show_all=args.all)
    if not memes:
        log.info("No hay memes pendientes de review.")
        return

    log.info(f"Generando grid con {len(memes)} memes...")
    html = generate_html(memes)
    REVIEW_HTML.write_text(html, encoding='utf-8')
    log.info(f"HTML generado: {REVIEW_HTML.name}")

    log.info(f"Servidor en http://127.0.0.1:{SERVER_PORT}")
    server = start_local_server()
    time.sleep(0.5)

    url = f"http://127.0.0.1:{SERVER_PORT}/review_page.html"
    webbrowser.open(url)
    log.info(f"Abierto: {url}")

    print("")
    print("=" * 60)
    print("   BATCH REVIEW")
    print("=" * 60)
    print(f"   {len(memes)} memes en el grid")
    print("")
    print("   1. Aprueba/rechaza en el navegador")
    print("   2. Click 'GUARDAR DECISIONES'")
    print("   3. Ctrl+C aqui para parar el servidor")
    print("   4. python batch_review.py --apply")
    print("")
    print(f"   Servidor: http://127.0.0.1:{SERVER_PORT}")
    print("   Ctrl+C para detener.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        log.info("Servidor detenido.")


if __name__ == "__main__":
    main()
