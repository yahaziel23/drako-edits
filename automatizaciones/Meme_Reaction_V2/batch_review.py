#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Batch Review (Grid Visual HTML)

Genera una pagina HTML con grid de thumbnails para aprobar/rechazar
memes rapidamente. Reemplaza el flujo de abrir imagen por imagen.

Flujo:
1. Genera review_page.html con thumbnails + botones
2. Abre en el navegador
3. Usuario aprueba/rechaza con click
4. Click "Guardar" -> descarga review_results.json
5. Script detecta el JSON -> actualiza SQLite
6. Limpia archivos temporales

Uso:
    python batch_review.py                    # Solo pendiente_review (frames)
    python batch_review.py --all              # Todo sin clasificar
    python batch_review.py --apply            # Lee JSON y aplica (sin generar HTML)
    python batch_review.py --status listo_clasificar  # Re-evaluar clasificados

Dependencias: ninguna extra (solo stdlib + utils)
"""

import sys
import os
import json
import base64
import argparse
import webbrowser
import http.server
import threading
import time
from pathlib import Path
from datetime import datetime

# Setup path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db, update_meme_status
from utils.config import load_config
from utils.logger import setup_logger, get_logger

# =============================================================================
# CONFIGURACION
# =============================================================================

MEMES_DIR = SCRIPT_DIR / "memes_descargados"
REVIEW_HTML = SCRIPT_DIR / "review_page.html"
REVIEW_RESULTS = SCRIPT_DIR / "review_results.json"
SERVER_PORT = 8765


# =============================================================================
# OBTENER MEMES PENDIENTES
# =============================================================================

def get_pending_memes(status_filter='pendiente_review', show_all=False):
    db = get_db()
    
    if show_all:
        rows = db.execute("""
            SELECT * FROM memes 
            WHERE status IN ('pendiente_review', 'listo_clasificar')
            ORDER BY likes DESC
        """).fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM memes 
            WHERE status = ?
            ORDER BY likes DESC
        """, (status_filter,)).fetchall()
    
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
            'status': row['status'],
            'image_path': str(img_path),
            'image_filename': f"{shortcode}.jpg",
        })
    
    return memes


# =============================================================================
# GENERAR HTML
# =============================================================================

def generate_html(memes):
    """
    Genera pagina HTML con grid de memes.
    Usa paths relativos a memes_descargados/ (servido por HTTP local).
    JavaScript usa event delegation (no inline onclick).
    """
    
    # Generar cards HTML
    cards_html = ""
    for meme in memes:
        likes_str = f"{meme['likes']:,}" if meme['likes'] else '?'
        # Path relativo: el server sirve desde SCRIPT_DIR
        img_src = f"memes_descargados/{meme['image_filename']}"
        
        cards_html += (
            f'<div class="card" data-sc="{meme["shortcode"]}">'
            f'<img src="{img_src}" alt="{meme["shortcode"]}" loading="lazy">'
            f'<div class="info">'
            f'<span class="sc">{meme["shortcode"][:11]}</span>'
            f'<span class="meta">{meme["source_type"]} | {likes_str} likes | @{meme["source_profile"]}</span>'
            f'</div>'
            f'<div class="btns">'
            f'<button class="ba" data-action="approve">SI</button>'
            f'<button class="br" data-action="reject">NO</button>'
            f'</div>'
            f'</div>\n'
        )
    
    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Batch Review - """ + str(len(memes)) + """ memes</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:system-ui,sans-serif; background:#1a1a2e; color:#eee; padding:20px; }
.header { text-align:center; margin-bottom:20px; padding:15px; background:#16213e; border-radius:10px; }
.header h1 { font-size:1.4em; margin-bottom:8px; }
.stats { display:flex; justify-content:center; gap:15px; font-size:0.9em; }
.stats span { padding:4px 12px; border-radius:15px; background:#0f3460; }
.toolbar { display:flex; justify-content:center; gap:10px; margin-bottom:20px; flex-wrap:wrap; }
.toolbar button { padding:10px 20px; border:none; border-radius:8px; cursor:pointer; font-size:0.95em; font-weight:bold; }
.btn-save { background:#00d4aa; color:#000; }
.btn-aa { background:#4CAF50; color:white; }
.btn-ra { background:#f44336; color:white; }
.btn-reset { background:#666; color:white; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px; }
.card { background:#16213e; border-radius:8px; overflow:hidden; border:3px solid transparent; transition:all 0.2s; }
.card.approved { border-color:#4CAF50; opacity:0.7; }
.card.rejected { border-color:#f44336; opacity:0.4; }
.card img { width:100%; height:180px; object-fit:cover; display:block; cursor:pointer; }
.card .info { padding:6px 8px; }
.card .sc { font-size:0.7em; color:#aaa; font-family:monospace; display:block; }
.card .meta { font-size:0.65em; color:#777; }
.card .btns { display:flex; }
.card .btns button { flex:1; padding:12px; border:none; cursor:pointer; font-size:1.1em; font-weight:bold; transition:background 0.15s; }
.ba { background:#1b4332; color:#4CAF50; }
.ba:hover { background:#2d6a4f; }
.br { background:#3d0000; color:#f44336; }
.br:hover { background:#660000; }
.zoom { display:none; position:fixed; top:0;left:0;right:0;bottom:0; background:rgba(0,0,0,0.92); z-index:1000; justify-content:center; align-items:center; cursor:pointer; }
.zoom.active { display:flex; }
.zoom img { max-width:90vw; max-height:90vh; object-fit:contain; }
</style>
</head>
<body>
<div class="header">
<h1>Batch Review - Meme Reaction V2</h1>
<div class="stats">
<span>Total: """ + str(len(memes)) + """</span>
<span id="sa">Aprobados: 0</span>
<span id="sr">Rechazados: 0</span>
<span id="sp">Pendientes: """ + str(len(memes)) + """</span>
</div>
</div>

<div class="toolbar">
<button class="btn-aa" id="approveAll">Aprobar Todos</button>
<button class="btn-ra" id="rejectAll">Rechazar Todos</button>
<button class="btn-reset" id="resetAll">Reset</button>
<button class="btn-save" id="saveBtn">GUARDAR DECISIONES</button>
</div>

<div class="grid" id="grid">
""" + cards_html + """
</div>

<div class="zoom" id="zoom">
<img id="zoomImg" src="">
</div>

<script>
(function() {
    var decisions = {};
    var grid = document.getElementById('grid');
    var zoom = document.getElementById('zoom');
    var zoomImg = document.getElementById('zoomImg');

    function updateStats() {
        var a = 0, r = 0;
        for (var k in decisions) {
            if (decisions[k] === 'approved') a++;
            if (decisions[k] === 'rejected') r++;
        }
        var total = grid.querySelectorAll('.card').length;
        document.getElementById('sa').textContent = 'Aprobados: ' + a;
        document.getElementById('sr').textContent = 'Rechazados: ' + r;
        document.getElementById('sp').textContent = 'Pendientes: ' + (total - a - r);
    }

    function setDecision(sc, decision) {
        decisions[sc] = decision;
        var card = grid.querySelector('[data-sc="' + sc + '"]');
        if (card) {
            card.className = 'card ' + decision;
        }
        updateStats();
    }

    // Event delegation on grid
    grid.addEventListener('click', function(e) {
        var btn = e.target.closest('[data-action]');
        if (btn) {
            var card = btn.closest('.card');
            var sc = card.getAttribute('data-sc');
            var action = btn.getAttribute('data-action');
            if (action === 'approve') setDecision(sc, 'approved');
            if (action === 'reject') setDecision(sc, 'rejected');
            return;
        }
        var img = e.target.closest('img');
        if (img && img.closest('.card')) {
            zoomImg.src = img.src;
            zoom.classList.add('active');
        }
    });

    zoom.addEventListener('click', function() {
        zoom.classList.remove('active');
    });

    document.getElementById('approveAll').addEventListener('click', function() {
        grid.querySelectorAll('.card').forEach(function(card) {
            var sc = card.getAttribute('data-sc');
            if (!decisions[sc]) setDecision(sc, 'approved');
        });
    });

    document.getElementById('rejectAll').addEventListener('click', function() {
        grid.querySelectorAll('.card').forEach(function(card) {
            var sc = card.getAttribute('data-sc');
            if (!decisions[sc]) setDecision(sc, 'rejected');
        });
    });

    document.getElementById('resetAll').addEventListener('click', function() {
        decisions = {};
        grid.querySelectorAll('.card').forEach(function(card) {
            card.className = 'card';
        });
        updateStats();
    });

    document.getElementById('saveBtn').addEventListener('click', function() {
        var total = Object.keys(decisions).length;
        if (total === 0) {
            alert('No has tomado ninguna decision.');
            return;
        }
        var data = {
            timestamp: new Date().toISOString(),
            total_decisions: total,
            decisions: decisions
        };
        var blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = 'review_results.json';
        a.click();
        URL.revokeObjectURL(url);
        alert('Guardado: ' + total + ' decisiones.\n\nAhora corre:\n  python batch_review.py --apply');
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') zoom.classList.remove('active');
    });

    console.log('Batch Review JS loaded. ' + grid.querySelectorAll('.card').length + ' cards.');
})();
</script>
</body>
</html>"""
    
    return html


# =============================================================================
# SERVIDOR HTTP LOCAL
# =============================================================================

def start_local_server():
    """
    Inicia un servidor HTTP local para servir las imagenes.
    Necesario porque file:// no permite cargar imagenes relativas en algunos browsers.
    """
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None  # Silenciar logs
    
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# =============================================================================
# APLICAR RESULTADOS
# =============================================================================

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
        log.error("  Descarga el archivo desde el navegador primero.")
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


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Batch Review - Grid Visual de Memes")
    parser.add_argument('--all', action='store_true',
                        help="Muestra TODOS los descargados sin clasificar")
    parser.add_argument('--status', type=str, default='pendiente_review',
                        help="Status a filtrar (default: pendiente_review)")
    parser.add_argument('--apply', action='store_true',
                        help="Solo aplica review_results.json sin generar HTML")
    parser.add_argument('--results-path', type=str, default=None,
                        help="Path especifico al JSON de resultados")
    args = parser.parse_args()

    # Setup
    setup_logger('batch_review')
    log = get_logger()
    load_config()
    init_db()

    # Modo: aplicar resultados
    if args.apply:
        apply_results(args.results_path)
        return

    # Modo: generar HTML
    memes = get_pending_memes(status_filter=args.status, show_all=args.all)

    if not memes:
        log.info("No hay memes pendientes de review.")
        log.info(f"  (filtro: status='{args.status}', --all={args.all})")
        return

    log.info(f"Generando grid con {len(memes)} memes...")

    # Generar HTML
    html = generate_html(memes)
    REVIEW_HTML.write_text(html, encoding='utf-8')
    log.info(f"HTML generado: {REVIEW_HTML.name}")

    # Iniciar servidor HTTP local
    log.info(f"Iniciando servidor en http://127.0.0.1:{SERVER_PORT}")
    server = start_local_server()
    time.sleep(0.5)

    # Abrir en navegador via HTTP (no file://)
    url = f"http://127.0.0.1:{SERVER_PORT}/review_page.html"
    webbrowser.open(url)
    log.info(f"Abierto: {url}")

    print("")
    print("=" * 60)
    print("   BATCH REVIEW")
    print("=" * 60)
    print(f"   {len(memes)} memes en el grid")
    print(f"")
    print(f"   1. Aprueba/rechaza en el navegador")
    print(f"   2. Click 'GUARDAR DECISIONES' (descarga JSON)")
    print(f"   3. Cierra esta terminal (Ctrl+C)")
    print(f"   4. Corre: python batch_review.py --apply")
    print(f"")
    print(f"   Servidor corriendo en puerto {SERVER_PORT}...")
    print(f"   Ctrl+C para detener.")
    print("=" * 60)

    # Mantener servidor vivo
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Servidor detenido.")
        server.shutdown()


if __name__ == "__main__":
    main()
