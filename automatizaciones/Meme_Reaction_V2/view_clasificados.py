#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - View Clasificados (QA Dashboard)

Genera un HTML interactivo para inspeccionar clasificaciones de la IA.
Permite verificar que los tags, descripcion e ideas son correctas
ANTES de pasar al match.

Acciones disponibles:
- Ver todas las propiedades de cada meme clasificado
- Reclasificar (marcar para re-run con prompt actual)
- Rechazar (mover a descartado)
- Notas/feedback (se guarda en user_feedback)
- Filtrar por confianza, categoria, perfil, prompt version

Uso:
    python view_clasificados.py                    # Muestra clasificados
    python view_clasificados.py --apply            # Aplica decisiones del JSON
    python view_clasificados.py --min-conf 0.5     # Solo confianza < 0.5
    python view_clasificados.py --categoria humor_dark  # Filtrar por tag
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
VIEW_HTML = SCRIPT_DIR / "view_clasificados.html"
VIEW_RESULTS = SCRIPT_DIR / "view_results.json"
SERVER_PORT = 8766


def get_classified_memes(min_conf=None, max_conf=None, categoria=None, version=None):
    """Obtiene memes clasificados con sus datos completos."""
    db = get_db()
    
    query = """
        SELECT m.shortcode, m.source_profile, m.source_type, m.likes, m.status,
               c.valido, c.es_video_real, c.confianza, c.categorias, c.descripcion,
               c.ideas_video, c.background_color, c.dia_especial, c.prompt_version,
               c.tokens_used, c.classified_at
        FROM memes m
        JOIN clasificaciones c ON m.shortcode = c.shortcode
        WHERE 1=1
    """
    params = []
    
    if min_conf is not None:
        query += " AND c.confianza >= ?"
        params.append(min_conf)
    if max_conf is not None:
        query += " AND c.confianza <= ?"
        params.append(max_conf)
    if version is not None:
        query += " AND c.prompt_version = ?"
        params.append(version)
    
    query += " ORDER BY c.confianza ASC, m.likes DESC"
    
    rows = db.execute(query, params).fetchall()
    
    memes = []
    for row in rows:
        shortcode = row['shortcode']
        img_path = MEMES_DIR / f"{shortcode}.jpg"
        if not img_path.exists():
            continue
        
        cats = json.loads(row['categorias']) if row['categorias'] else []
        ideas = json.loads(row['ideas_video']) if row['ideas_video'] else []
        
        # Filtrar por categoria si se especifica
        if categoria and categoria not in cats:
            continue
        
        memes.append({
            'shortcode': shortcode,
            'source_profile': row['source_profile'] or '?',
            'source_type': row['source_type'] or '?',
            'likes': row['likes'] or 0,
            'status': row['status'],
            'valido': row['valido'],
            'es_video_real': row['es_video_real'],
            'confianza': row['confianza'] or 0.0,
            'categorias': cats,
            'descripcion': row['descripcion'] or '',
            'ideas_video': ideas,
            'background_color': row['background_color'] or '#000000',
            'dia_especial': row['dia_especial'],
            'prompt_version': row['prompt_version'],
            'tokens_used': row['tokens_used'] or 0,
            'classified_at': row['classified_at'] or '',
        })
    
    return memes


def generate_html(memes):
    """Genera HTML de QA dashboard."""
    
    # Build cards
    cards = []
    for m in memes:
        sc = m['shortcode']
        likes_str = f"{m['likes']:,}" if m['likes'] else '?'
        conf_pct = int(m['confianza'] * 100)
        conf_color = '#4CAF50' if conf_pct >= 80 else '#ff9800' if conf_pct >= 50 else '#f44336'
        
        # Tags as pills
        tags_html = ''
        for tag in m['categorias']:
            tags_html += '<span class="tag">' + tag + '</span>'
        
        # Ideas as list
        ideas_html = ''
        for idx, idea in enumerate(m['ideas_video'], 1):
            ideas_html += '<li class="idea-item" data-sc="' + sc + '" data-idx="' + str(idx) + '" onclick="pickIdea(\'' + sc + '\',' + str(idx) + ')">' + str(idx) + '. ' + idea + '</li>'
        
        # Status badge
        valid_badge = '<span class="badge ok">VALIDO</span>' if m['valido'] else '<span class="badge bad">INVALIDO</span>'
        if m['es_video_real']:
            valid_badge += '<span class="badge warn">VIDEO_REAL</span>'
        
        # Escape description for HTML
        desc_safe = m['descripcion'].replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        
        card = (
            '<div class="card" id="c-' + sc + '" data-sc="' + sc + '">'
            '<div class="card-top">'
            '<img src="memes_descargados/' + sc + '.jpg" onclick="zoomIn(this.src)">'
            '<div class="card-actions">'
            '<button class="btn-ok" onclick="markOk(\'' + sc + '\')">OK</button>'
            '<button class="btn-re" onclick="markReclassify(\'' + sc + '\')">RECLASIFICAR</button>'
            '<button class="btn-no" onclick="markReject(\'' + sc + '\')">RECHAZAR</button>'
            '<button class="btn-ni" onclick="markNewIdeas(\'' + sc + '\')">5 NUEVAS</button>'
            '</div>'
            '</div>'
            '<div class="card-body">'
            '<div class="card-header">'
            '<span class="sc-code">' + sc[:11] + '</span>'
            '<span class="conf" style="color:' + conf_color + '">' + str(conf_pct) + '%</span>'
            + valid_badge +
            '</div>'
            '<div class="meta-row">'
            '<span>' + m['source_type'] + ' | ' + likes_str + ' likes | @' + m['source_profile'] + '</span>'
            '<span class="pv">prompt v' + str(m['prompt_version']) + '</span>'
            '</div>'
            '<div class="tags">' + tags_html + '</div>'
            '<div class="desc">' + desc_safe + '</div>'
            '<details><summary>5 Ideas de Video</summary><ol class="ideas">' + ideas_html + '</ol></details>'
            '<div class="bg-color">Fondo: <span class="color-swatch" style="background:' + m['background_color'] + '"></span> ' + m['background_color'] + '</div>'
            + ('<div class="dia">Dia especial: ' + str(m['dia_especial']) + '</div>' if m['dia_especial'] else '') +
            '<textarea class="notes" placeholder="Notas/feedback (opcional)..." data-sc="' + sc + '"></textarea>'
            '</div>'
            '</div>'
        )
        cards.append(card)
    
    cards_html = '\n'.join(cards)
    total = str(len(memes))
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>View Clasificados - ' + total + ' memes</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,sans-serif;background:#0f0f1a;color:#eee;padding:20px}')
    html_parts.append('.hdr{text-align:center;margin-bottom:20px;padding:15px;background:#1a1a2e;border-radius:10px}')
    html_parts.append('.hdr h1{font-size:1.4em;margin-bottom:8px}')
    html_parts.append('.stats{display:flex;justify-content:center;gap:12px;font-size:0.85em;flex-wrap:wrap}')
    html_parts.append('.stats span{padding:4px 12px;border-radius:15px;background:#0f3460}')
    html_parts.append('.tb{display:flex;justify-content:center;gap:10px;margin-bottom:20px}')
    html_parts.append('.tb button{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:0.95em;font-weight:bold}')
    html_parts.append('.sv{background:#00d4aa;color:#000}')
    html_parts.append('.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(350px,1fr));gap:15px}')
    html_parts.append('.card{background:#1a1a2e;border-radius:10px;overflow:hidden;border:2px solid transparent;transition:all 0.2s}')
    html_parts.append('.card.marked-ok{border-color:#4CAF50;opacity:0.8}')
    html_parts.append('.card.marked-reclassify{border-color:#ff9800}')
    html_parts.append('.card.marked-reject{border-color:#f44336;opacity:0.5}')
    html_parts.append('.card-top{position:relative}')
    html_parts.append('.card-top img{width:100%;height:200px;object-fit:contain;background:#000;display:block;cursor:pointer}')
    html_parts.append('.card-actions{position:absolute;bottom:5px;right:5px;display:flex;gap:4px}')
    html_parts.append('.card-actions button{padding:5px 10px;border:none;border-radius:5px;cursor:pointer;font-size:0.75em;font-weight:bold}')
    html_parts.append('.btn-ok{background:#4CAF50;color:white}')
    html_parts.append('.btn-re{background:#ff9800;color:white}')
    html_parts.append('.btn-no{background:#f44336;color:white}')
    html_parts.append('.card-body{padding:10px}')
    html_parts.append('.card-header{display:flex;align-items:center;gap:8px;margin-bottom:5px}')
    html_parts.append('.sc-code{font-family:monospace;font-size:0.75em;color:#aaa}')
    html_parts.append('.conf{font-weight:bold;font-size:1.1em}')
    html_parts.append('.badge{font-size:0.65em;padding:2px 6px;border-radius:8px;font-weight:bold}')
    html_parts.append('.badge.ok{background:#1b4332;color:#4CAF50}')
    html_parts.append('.badge.bad{background:#3d0000;color:#f44336}')
    html_parts.append('.badge.warn{background:#3d2800;color:#ff9800}')
    html_parts.append('.meta-row{font-size:0.7em;color:#888;display:flex;justify-content:space-between;margin-bottom:8px}')
    html_parts.append('.pv{color:#666}')
    html_parts.append('.tags{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px}')
    html_parts.append('.tag{font-size:0.65em;padding:2px 8px;border-radius:10px;background:#0f3460;color:#6db3f8}')
    html_parts.append('.desc{font-size:0.78em;color:#ccc;margin-bottom:8px;line-height:1.4;max-height:80px;overflow-y:auto}')
    html_parts.append('details{margin-bottom:8px}')
    html_parts.append('summary{font-size:0.75em;color:#aaa;cursor:pointer}')
    html_parts.append('.ideas{font-size:0.72em;color:#bbb;padding-left:15px;margin-top:5px}')
    html_parts.append('.ideas li{margin-bottom:4px;line-height:1.3;cursor:pointer;padding:3px 5px;border-radius:4px;transition:background 0.15s}')
    html_parts.append('.ideas li:hover{background:#1a3a5c}')
    html_parts.append('.ideas li.picked{background:#1b4332;border-left:3px solid #4CAF50}')
    html_parts.append('.bg-color{font-size:0.7em;color:#888;display:flex;align-items:center;gap:5px;margin-bottom:5px}')
    html_parts.append('.color-swatch{width:14px;height:14px;border-radius:3px;border:1px solid #555;display:inline-block}')
    html_parts.append('.dia{font-size:0.7em;color:#ff9800;margin-bottom:5px}')
    html_parts.append('.notes{width:100%;height:40px;background:#0f0f1a;border:1px solid #333;border-radius:5px;color:#eee;padding:5px;font-size:0.75em;resize:vertical}')
    html_parts.append('.zo{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.92);z-index:1000;justify-content:center;align-items:center;cursor:pointer}')
    html_parts.append('.zo.active{display:flex}')
    html_parts.append('.zo img{max-width:90vw;max-height:90vh;object-fit:contain}')
    html_parts.append('</style></head><body>')
    html_parts.append('<div class="hdr"><h1>View Clasificados - QA Dashboard</h1>')
    html_parts.append('<div class="stats"><span>Total: ' + total + '</span>')
    html_parts.append('<span id="sok">OK: 0</span>')
    html_parts.append('<span id="sre">Reclasificar: 0</span>')
    html_parts.append('<span id="srj">Rechazar: 0</span></div></div>')
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveResults()">GUARDAR DECISIONES</button>')
    html_parts.append('</div>')
    html_parts.append('<div class="grid">' + cards_html + '</div>')
    html_parts.append('<div class="zo" id="zo" onclick="this.classList.remove(\'active\')">')
    html_parts.append('<img id="zi" src=""></div>')
    # === JAVASCRIPT (clean block) ===
    js_code = """
<script>
var D = {};
var notes = {};
var picks = {};

function markOk(sc) {
    D[sc] = "ok";
    document.getElementById("c-" + sc).className = "card marked-ok";
    upd();
}
function markReclassify(sc) {
    D[sc] = "reclassify";
    document.getElementById("c-" + sc).className = "card marked-reclassify";
    upd();
}
function markReject(sc) {
    D[sc] = "reject";
    document.getElementById("c-" + sc).className = "card marked-reject";
    upd();
}
function markNewIdeas(sc) {
    D[sc] = "new_ideas";
    document.getElementById("c-" + sc).className = "card marked-reclassify";
    upd();
}
function pickIdea(sc, idx) {
    picks[sc] = idx;
    var card = document.getElementById("c-" + sc);
    var items = card.querySelectorAll(".idea-item");
    for (var i = 0; i < items.length; i++) {
        items[i].classList.remove("picked");
    }
    var sel = card.querySelector('[data-idx="' + idx + '"]');
    if (sel) sel.classList.add("picked");
}
function zoomIn(src) {
    document.getElementById("zi").src = src;
    document.getElementById("zo").classList.add("active");
}
function upd() {
    var ok = 0, re = 0, rj = 0, ni = 0;
    for (var k in D) {
        if (D[k] === "ok") ok++;
        if (D[k] === "reclassify") re++;
        if (D[k] === "reject") rj++;
        if (D[k] === "new_ideas") ni++;
    }
    document.getElementById("sok").textContent = "OK: " + ok;
    document.getElementById("sre").textContent = "Reclasificar: " + re;
    document.getElementById("srj").textContent = "Rechazar: " + rj;
}
function saveResults() {
    document.querySelectorAll(".notes").forEach(function(ta) {
        if (ta.value.trim()) notes[ta.dataset.sc] = ta.value.trim();
    });
    var t = Object.keys(D).length;
    var data = {
        timestamp: new Date().toISOString(),
        total_decisions: t,
        decisions: D,
        feedback: notes,
        idea_picks: picks
    };
    var blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "view_results.json";
    a.click();
    URL.revokeObjectURL(url);
    var msg = "Guardado: " + t + " decisiones, " + Object.keys(notes).length + " notas, " + Object.keys(picks).length + " ideas seleccionadas.";
    msg += "\n\nCorre: python view_clasificados.py --apply";
    alert(msg);
}
console.log("ViewClasificados OK: " + document.querySelectorAll(".card").length + " cards");
</script></body></html>
"""
    html_parts.append(js_code)
    
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
    """Aplica decisiones del QA review."""
    log = get_logger()
    path = Path(results_path) if results_path else VIEW_RESULTS
    downloads_path = Path.home() / "Downloads" / "view_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
    else:
        log.error("No se encontro view_results.json")
        log.error(f"  Buscado en: {VIEW_RESULTS}")
        log.error(f"  Buscado en: {downloads_path}")
        return
    
    decisions = data.get('decisions', {})
    feedback = data.get('feedback', {})
    db = get_db()
    
    ok_count = 0
    reclassify_count = 0
    reject_count = 0
    new_ideas_count = 0
    feedback_count = 0
    
    for shortcode, decision in decisions.items():
        if decision == 'ok':
            # Confirmar clasificacion - no cambiar status
            ok_count += 1
        elif decision == 'reclassify':
            # Devolver a listo_clasificar para re-clasificar
            update_meme_status(shortcode, 'listo_clasificar')
            # Borrar clasificacion anterior
            db.execute("DELETE FROM clasificaciones WHERE shortcode = ?", (shortcode,))
            reclassify_count += 1
        elif decision == 'reject':
            # Mover a descartado
            update_meme_status(shortcode, 'descartado_ia')
            reject_count += 1
        elif decision == 'new_ideas':
            # Marcar para regenerar solo ideas (mantiene tags/descripcion)
            db.execute(
                "UPDATE clasificaciones SET ideas_video = '[]' WHERE shortcode = ?",
                (shortcode,)
            )
            update_meme_status(shortcode, 'listo_clasificar')
            new_ideas_count += 1
    
    # Guardar idea picks (idea favorita seleccionada por el usuario)
    idea_picks = data.get('idea_picks', {})
    for shortcode, idx in idea_picks.items():
        db.execute(
            "UPDATE clasificaciones SET ideas_video = json_set(COALESCE(ideas_video,'[]'), '$.picked', ?) WHERE shortcode = ?",
            (int(idx), shortcode)
        )
    picks_count = len(idea_picks)

    # Guardar feedback
    for shortcode, note in feedback.items():
        if note.strip():
            # Delete old feedback for this shortcode+step to avoid duplicates
            db.execute(
                "DELETE FROM user_feedback WHERE shortcode = ? AND step = 'classify_qa'",
                (shortcode,)
            )
            db.execute("""
                INSERT INTO user_feedback (shortcode, step, user_said, decision)
                VALUES (?, 'classify_qa', ?, 'feedback')
            """, (shortcode, note))
            feedback_count += 1
    
    db.commit()
    
    log.info("")
    log.info("=" * 50)
    log.info("   VIEW CLASIFICADOS - APLICADO")
    log.info("=" * 50)
    log.info(f"   OK (confirmados):        {ok_count}")
    log.info(f"   Ideas seleccionadas:     {picks_count}")
    log.info(f"   Reclasificar:            {reclassify_count}")
    log.info(f"   Nuevas ideas:            {new_ideas_count}")
    log.info(f"   Rechazados:              {reject_count}")
    log.info(f"   Notas guardadas:         {feedback_count}")
    log.info("=" * 50)
    if reclassify_count > 0 or new_ideas_count > 0:
        total_re = reclassify_count + new_ideas_count
        log.info(f"   {total_re} memes listos para re-clasificar.")
        log.info(f"   Corre: python 3_classify_meme.py")
    log.info("")
    
    if path.exists():
        path.unlink()


def main():
    parser = argparse.ArgumentParser(description="View Clasificados - QA Dashboard")
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--min-conf', type=float, default=None,
                        help="Filtrar confianza minima")
    parser.add_argument('--max-conf', type=float, default=None,
                        help="Filtrar confianza maxima")
    parser.add_argument('--categoria', type=str, default=None,
                        help="Filtrar por categoria")
    parser.add_argument('--version', type=int, default=None,
                        help="Filtrar por prompt version")
    parser.add_argument('--results-path', type=str, default=None)
    args = parser.parse_args()

    setup_logger('view_clasificados')
    log = get_logger()
    load_config()
    init_db()

    if args.apply:
        apply_results(args.results_path)
        return

    memes = get_classified_memes(
        min_conf=args.min_conf,
        max_conf=args.max_conf,
        categoria=args.categoria,
        version=args.version
    )

    if not memes:
        log.info("No hay memes clasificados para mostrar.")
        return

    log.info(f"Generando dashboard con {len(memes)} memes clasificados...")
    html = generate_html(memes)
    VIEW_HTML.write_text(html, encoding='utf-8')
    log.info(f"HTML generado: {VIEW_HTML.name}")

    log.info(f"Servidor en http://127.0.0.1:{SERVER_PORT}")
    server = start_local_server()
    time.sleep(0.5)

    url = f"http://127.0.0.1:{SERVER_PORT}/view_clasificados.html"
    webbrowser.open(url)

    print("")
    print("=" * 60)
    print("   VIEW CLASIFICADOS - QA DASHBOARD")
    print("=" * 60)
    print(f"   {len(memes)} memes clasificados")
    print("")
    print("   Ordenados por confianza BAJA primero (los mas dudosos arriba)")
    print("")
    print("   Acciones:")
    print("     OK           = clasificacion correcta (sin cambios)")
    print("     RECLASIFICAR = vuelve a cola de clasificacion")
    print("     RECHAZAR     = descartado")
    print("     Notas        = feedback para mejorar prompts")
    print("")
    print("   1. Revisa cada meme")
    print("   2. Click 'GUARDAR DECISIONES'")
    print("   3. Ctrl+C aqui")
    print("   4. python view_clasificados.py --apply")
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
