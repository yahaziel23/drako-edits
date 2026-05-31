#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Batch Review (Grid Visual HTML)

Genera una página HTML con grid de thumbnails para aprobar/rechazar
memes rápidamente. Reemplaza el flujo de abrir imagen por imagen.

Flujo:
1. Genera review_page.html con thumbnails + botones
2. Abre en el navegador
3. Usuario aprueba/rechaza con click
4. Click "Guardar" → escribe review_results.json
5. Script detecta el JSON → actualiza SQLite
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


# =============================================================================
# OBTENER MEMES PENDIENTES
# =============================================================================

def get_pending_memes(status_filter='pendiente_review', show_all=False):
    """
    Obtiene memes a mostrar en el grid.
    Returns: list of dicts con info de cada meme.
    """
    db = get_db()
    
    if show_all:
        # Todo lo descargado que aún no está clasificado
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
        })
    
    return memes


# =============================================================================
# GENERAR HTML
# =============================================================================

def image_to_base64(image_path):
    """Convierte imagen a base64 data URI para embeber en HTML."""
    with open(image_path, 'rb') as f:
        data = base64.b64encode(f.read()).decode('utf-8')
    return f"data:image/jpeg;base64,{data}"


def generate_html(memes):
    """
    Genera página HTML con grid de memes.
    Cada thumbnail tiene botones de aprobar/rechazar.
    Al guardar, escribe un JSON con las decisiones.
    """
    
    # Generar cards HTML
    cards_html = ""
    for meme in memes:
        b64 = image_to_base64(meme['image_path'])
        likes_str = f"{meme['likes']:,}" if meme['likes'] else '?'
        
        cards_html += f"""
        <div class="card" id="card-{meme['shortcode']}" data-shortcode="{meme['shortcode']}">
            <img src="{b64}" alt="{meme['shortcode']}" onclick="toggleZoom(this)">
            <div class="info">
                <span class="shortcode">{meme['shortcode'][:11]}</span>
                <span class="meta">{meme['source_type']} | {likes_str} \u2764\ufe0f | @{meme['source_profile']}</span>
            </div>
            <div class="buttons">
                <button class="btn-approve" onclick="approve('{meme['shortcode']}')">\u2705</button>
                <button class="btn-reject" onclick="reject('{meme['shortcode']}')">\u274c</button>
            </div>
        </div>
        """
    
    # Página completa
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Meme Reaction V2 - Batch Review ({len(memes)} memes)</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 20px;
            padding: 15px;
            background: #16213e;
            border-radius: 10px;
        }}
        .header h1 {{ font-size: 1.5em; margin-bottom: 5px; }}
        .stats {{
            display: flex;
            justify-content: center;
            gap: 20px;
            margin-top: 10px;
            font-size: 0.9em;
        }}
        .stats span {{ padding: 4px 12px; border-radius: 15px; background: #0f3460; }}
        .toolbar {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 20px;
        }}
        .toolbar button {{
            padding: 10px 25px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1em;
            font-weight: bold;
        }}
        .btn-save {{ background: #00d4aa; color: #000; }}
        .btn-save:hover {{ background: #00f5c4; }}
        .btn-approve-all {{ background: #4CAF50; color: white; }}
        .btn-reject-all {{ background: #f44336; color: white; }}
        .btn-reset {{ background: #666; color: white; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 12px;
        }}
        .card {{
            background: #16213e;
            border-radius: 10px;
            overflow: hidden;
            border: 3px solid transparent;
            transition: all 0.2s;
        }}
        .card.approved {{ border-color: #4CAF50; opacity: 0.7; }}
        .card.rejected {{ border-color: #f44336; opacity: 0.5; }}
        .card img {{
            width: 100%;
            height: 200px;
            object-fit: cover;
            cursor: pointer;
        }}
        .card .info {{
            padding: 8px;
            display: flex;
            flex-direction: column;
            gap: 3px;
        }}
        .card .shortcode {{ font-size: 0.75em; color: #aaa; font-family: monospace; }}
        .card .meta {{ font-size: 0.7em; color: #888; }}
        .card .buttons {{
            display: flex;
            gap: 0;
        }}
        .card .buttons button {{
            flex: 1;
            padding: 10px;
            border: none;
            cursor: pointer;
            font-size: 1.4em;
            transition: background 0.2s;
        }}
        .btn-approve {{ background: #1b4332; }}
        .btn-approve:hover {{ background: #2d6a4f; }}
        .btn-reject {{ background: #3d0000; }}
        .btn-reject:hover {{ background: #660000; }}
        .zoom-overlay {{
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.9);
            z-index: 1000;
            justify-content: center;
            align-items: center;
            cursor: pointer;
        }}
        .zoom-overlay img {{
            max-width: 90vw;
            max-height: 90vh;
            object-fit: contain;
        }}
        .zoom-overlay.active {{ display: flex; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>\ud83d\uddbc\ufe0f Batch Review - Meme Reaction V2</h1>
        <div class="stats">
            <span>Total: {len(memes)}</span>
            <span id="stat-approved">\u2705 0</span>
            <span id="stat-rejected">\u274c 0</span>
            <span id="stat-pending">\u23f3 {len(memes)}</span>
        </div>
    </div>
    
    <div class="toolbar">
        <button class="btn-approve-all" onclick="approveAll()">\u2705 Aprobar Todos</button>
        <button class="btn-reject-all" onclick="rejectAll()">\u274c Rechazar Todos</button>
        <button class="btn-reset" onclick="resetAll()">\ud83d\udd04 Reset</button>
        <button class="btn-save" onclick="saveResults()">\ud83d\udcbe GUARDAR DECISIONES</button>
    </div>
    
    <div class="grid">
        {cards_html}
    </div>
    
    <div class="zoom-overlay" id="zoomOverlay" onclick="closeZoom()">
        <img id="zoomImage" src="">
    </div>
    
    <script>
        const decisions = {{}};
        
        function approve(shortcode) {{
            decisions[shortcode] = 'approved';
            const card = document.getElementById('card-' + shortcode);
            card.className = 'card approved';
            updateStats();
        }}
        
        function reject(shortcode) {{
            decisions[shortcode] = 'rejected';
            const card = document.getElementById('card-' + shortcode);
            card.className = 'card rejected';
            updateStats();
        }}
        
        function approveAll() {{
            document.querySelectorAll('.card').forEach(card => {{
                const sc = card.dataset.shortcode;
                if (!decisions[sc]) {{
                    approve(sc);
                }}
            }});
        }}
        
        function rejectAll() {{
            document.querySelectorAll('.card').forEach(card => {{
                const sc = card.dataset.shortcode;
                if (!decisions[sc]) {{
                    reject(sc);
                }}
            }});
        }}
        
        function resetAll() {{
            Object.keys(decisions).forEach(sc => delete decisions[sc]);
            document.querySelectorAll('.card').forEach(card => {{
                card.className = 'card';
            }});
            updateStats();
        }}
        
        function updateStats() {{
            const approved = Object.values(decisions).filter(d => d === 'approved').length;
            const rejected = Object.values(decisions).filter(d => d === 'rejected').length;
            const total = document.querySelectorAll('.card').length;
            const pending = total - approved - rejected;
            document.getElementById('stat-approved').textContent = '\u2705 ' + approved;
            document.getElementById('stat-rejected').textContent = '\u274c ' + rejected;
            document.getElementById('stat-pending').textContent = '\u23f3 ' + pending;
        }}
        
        function toggleZoom(img) {{
            const overlay = document.getElementById('zoomOverlay');
            document.getElementById('zoomImage').src = img.src;
            overlay.classList.add('active');
        }}
        
        function closeZoom() {{
            document.getElementById('zoomOverlay').classList.remove('active');
        }}
        
        function saveResults() {{
            const total = Object.keys(decisions).length;
            if (total === 0) {{
                alert('No has tomado ninguna decisi\u00f3n a\u00fan.');
                return;
            }}
            
            const data = {{
                timestamp: new Date().toISOString(),
                total_decisions: total,
                decisions: decisions
            }};
            
            // Crear archivo descargable
            const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'review_results.json';
            a.click();
            URL.revokeObjectURL(url);
            
            alert(`\u2705 Guardado: ${{total}} decisiones.\n\nAhora corre:\n  python batch_review.py --apply\n\nPara aplicar los cambios a la DB.`);
        }}
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeZoom();
        }});
    </script>
</body>
</html>"""
    
    return html


# =============================================================================
# APLICAR RESULTADOS
# =============================================================================

def apply_results(results_path=None):
    """
    Lee review_results.json y actualiza SQLite.
    - approved → status = 'listo_clasificar'
    - rejected → status = 'rechazado'
    """
    log = get_logger()
    path = Path(results_path) if results_path else REVIEW_RESULTS
    
    # Buscar también en Downloads (donde el navegador descarga)
    downloads_path = Path.home() / "Downloads" / "review_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
        log.info(f"Encontrado en Downloads: {path}")
    else:
        log.error(f"No se encontró review_results.json")
        log.error(f"  Buscado en: {REVIEW_RESULTS}")
        log.error(f"  Buscado en: {downloads_path}")
        log.error(f"  Descarga el archivo desde el navegador primero.")
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
    
    log.info(f"")
    log.info(f"=" * 50)
    log.info(f"   BATCH REVIEW APLICADO")
    log.info(f"=" * 50)
    log.info(f"   Aprobados (\u2192 listo_clasificar): {approved}")
    log.info(f"   Rechazados (\u2192 rechazado):       {rejected}")
    log.info(f"   Total decisiones:                {len(decisions)}")
    log.info(f"=" * 50)
    
    # Limpiar JSON después de aplicar
    if path.exists():
        path.unlink()
        log.info(f"   JSON limpiado: {path.name}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Batch Review - Grid Visual de Memes")
    parser.add_argument('--all', action='store_true',
                        help="Muestra TODOS los descargados sin clasificar (no solo frames)")
    parser.add_argument('--status', type=str, default='pendiente_review',
                        help="Status a filtrar (default: pendiente_review)")
    parser.add_argument('--apply', action='store_true',
                        help="Solo aplica review_results.json sin generar HTML")
    parser.add_argument('--results-path', type=str, default=None,
                        help="Path específico al JSON de resultados")
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

    # Abrir en navegador
    webbrowser.open(str(REVIEW_HTML))
    log.info("Abierto en navegador.")

    print("")
    print("=" * 60)
    print("   BATCH REVIEW")
    print("=" * 60)
    print(f"   {len(memes)} memes en el grid")
    print(f"")
    print(f"   1. Aprueba/rechaza en el navegador")
    print(f"   2. Click 'GUARDAR DECISIONES' (descarga JSON)")
    print(f"   3. Corre: python batch_review.py --apply")
    print(f"")
    print(f"   Eso actualizar\u00e1 SQLite y los aprobados pasar\u00e1n")
    print(f"   a 'listo_clasificar' para el paso 3 (IA).")
    print("=" * 60)


if __name__ == "__main__":
    main()
