#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Catalogo de Matches (Interfaz de Decision)

Interfaz HTML meme-por-meme para decidir matches finales.
Por cada meme muestra:
  - Imagen del meme (grande, clickeable para zoom)
  - Top clips con video preview + compatibilidad + captions
  - Clips auto-aceptados marcados en verde
  - Opcion de editar caption inline
  - Opcion de skip / regenerar / editar descripcion
  - Sugerencias de YouTube si no hay buen match
  - Progreso general

Todas las decisiones se guardan en user_feedback para entrenamiento futuro.

Uso:
    python catalogo_matches.py                 # Ver todos los matches
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
from urllib.parse import parse_qs

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db
from utils.config import load_config
from utils.logger import setup_logger, get_logger

MEMES_DIR = SCRIPT_DIR / "memes_descargados"
CLIPS_DIR = SCRIPT_DIR / "clips"
MATCH_HTML = SCRIPT_DIR / "catalogo_matches.html"
SERVER_PORT = 8768


def get_matches_for_review():
    """Obtiene memes con matches listos para revision (TODOS incluyendo auto-aceptados)."""
    db = get_db()
    
    memes = db.execute("""
        SELECT m.shortcode, m.image_path, m.status,
               c.descripcion, c.categorias, c.ideas_video, c.confianza
        FROM memes m
        JOIN clasificaciones c ON m.shortcode = c.shortcode
        WHERE m.status IN ('match_review', 'buscar_clip', 'por_generar')
        ORDER BY 
            CASE m.status 
                WHEN 'por_generar' THEN 1
                WHEN 'match_review' THEN 2
                WHEN 'buscar_clip' THEN 3 
            END
    """).fetchall()
    
    results = []
    for meme in memes:
        matches = db.execute("""
            SELECT clip_id, accuracy, caption, match_rank, razon, 
                   captions_json, youtube_sugerencias
            FROM matches
            WHERE shortcode = ?
            ORDER BY match_rank ASC
        """, (meme['shortcode'],)).fetchall()
        
        cats = []
        try:
            cats = json.loads(meme['categorias']) if meme['categorias'] else []
        except Exception:
            pass
        
        ideas = []
        try:
            ideas = json.loads(meme['ideas_video']) if meme['ideas_video'] else []
        except Exception:
            pass
        
        # Find meme image - check memes_descargados/ with common extensions
        image_file = None
        for ext in ['.jpg', '.png', '.webp']:
            candidate = MEMES_DIR / (meme['shortcode'] + ext)
            if candidate.exists():
                image_file = 'memes_descargados/' + meme['shortcode'] + ext
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
            
            clip_row = db.execute("""
                SELECT filename, descripcion_corta, mood, intensidad, descripcion
                FROM clips WHERE id = ?
            """, (m['clip_id'],)).fetchone()
            
            clip_file = None
            clip_desc = ''
            clip_mood = ''
            clip_full_desc = ''
            clip_intensidad = 5
            if clip_row:
                clip_file = 'clips/' + clip_row['filename']
                clip_desc = clip_row['descripcion_corta'] or ''
                clip_mood = clip_row['mood'] or ''
                clip_full_desc = clip_row['descripcion'] or ''
                clip_intensidad = clip_row['intensidad'] or 5
            
            match_list.append({
                'clip_id': m['clip_id'],
                'score': m['accuracy'],
                'razon': m['razon'] or '',
                'captions': captions,
                'clip_file': clip_file,
                'clip_desc': clip_desc,
                'clip_full_desc': clip_full_desc,
                'clip_mood': clip_mood,
                'clip_intensidad': clip_intensidad,
            })
        
        results.append({
            'shortcode': meme['shortcode'],
            'image_file': image_file,
            'status': meme['status'],
            'descripcion': meme['descripcion'] or '',
            'categorias': cats,
            'ideas': ideas,
            'confianza': meme['confianza'] or 0,
            'matches': match_list,
            'youtube_sugs': youtube_sugs,
        })
    
    return results


def generate_html(memes_data):
    """Genera HTML completo del catalogo de matches con mejoras QoL."""
    total = len(memes_data)
    auto_count = sum(1 for m in memes_data if m['status'] == 'por_generar')
    review_count = sum(1 for m in memes_data if m['status'] == 'match_review')
    no_match_count = sum(1 for m in memes_data if m['status'] == 'buscar_clip')
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>Match Meme-Clip | ' + str(total) + ' memes</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a12;color:#eee;padding:16px 24px}')
    html_parts.append('::-webkit-scrollbar{width:6px}::-webkit-scrollbar-thumb{background:#333;border-radius:3px}')
    # Header
    html_parts.append('.hdr{text-align:center;margin-bottom:16px;padding:12px 20px;background:linear-gradient(135deg,#12122a,#1a1a3a);border-radius:12px;border:1px solid #222}')
    html_parts.append('.hdr h1{font-size:1.2em;margin-bottom:4px;color:#fff}')
    html_parts.append('.stats{font-size:0.75em;color:#888;display:flex;justify-content:center;gap:16px}')
    html_parts.append('.stat-pill{padding:3px 10px;border-radius:12px;font-weight:600}')
    html_parts.append('.pill-green{background:#1a3a1a;color:#4CAF50}.pill-orange{background:#3a2a0a;color:#ff9800}.pill-red{background:#3a1a1a;color:#f44336}')
    # Toolbar
    html_parts.append('.tb{display:flex;justify-content:center;gap:8px;margin-bottom:16px;flex-wrap:wrap}')
    html_parts.append('.tb button{padding:8px 16px;border:1px solid #333;background:#1a1a2e;color:#ddd;border-radius:8px;cursor:pointer;font-size:0.8em;transition:all 0.15s}')
    html_parts.append('.tb button:hover{background:#2a2a4e;border-color:#555}')
    html_parts.append('.tb .sv{background:#00d4aa;color:#000;border-color:#00d4aa;font-weight:bold}')
    html_parts.append('.tb .sv:hover{background:#00f0c0}')
    # Filters
    html_parts.append('.filters{display:flex;justify-content:center;gap:6px;margin-bottom:14px}')
    html_parts.append('.filters button{padding:5px 12px;border:1px solid #333;background:transparent;color:#888;border-radius:16px;cursor:pointer;font-size:0.7em;transition:all 0.15s}')
    html_parts.append('.filters button.active{border-color:#00d4aa;color:#00d4aa;background:#0a2a2a}')
    # Cards
    html_parts.append('.meme-card{display:flex;gap:16px;background:#12122a;border-radius:12px;padding:16px;margin-bottom:14px;border:2px solid #1a1a2a;transition:all 0.3s}')
    html_parts.append('.meme-card.decided{border-color:#4CAF50;opacity:0.85}')
    html_parts.append('.meme-card.skipped{border-color:#ff9800;opacity:0.6}')
    html_parts.append('.meme-card.auto-accepted{border-left:4px solid #4CAF50}')
    html_parts.append('.meme-card[data-status="buscar_clip"]{border-left:4px solid #f44336}')
    # Left panel (meme)
    html_parts.append('.meme-left{width:300px;min-width:300px;display:flex;flex-direction:column;gap:6px}')
    html_parts.append('.meme-img{width:100%;max-height:350px;object-fit:contain;border-radius:8px;cursor:pointer;background:#000;border:1px solid #222}')
    html_parts.append('.meme-img:hover{border-color:#00d4aa}')
    html_parts.append('.no-img{width:100%;height:200px;display:flex;align-items:center;justify-content:center;background:#1a1a2a;border-radius:8px;color:#555;font-size:0.8em}')
    html_parts.append('.meme-meta{display:flex;gap:6px;align-items:center;flex-wrap:wrap}')
    html_parts.append('.sc{font-family:monospace;font-size:0.65em;color:#555}')
    html_parts.append('.badge{font-size:0.6em;padding:2px 7px;border-radius:10px;font-weight:600}')
    html_parts.append('.badge-auto{background:#1a3a1a;color:#4CAF50;border:1px solid #2a5a2a}')
    html_parts.append('.badge-review{background:#3a2a0a;color:#ff9800;border:1px solid #5a4a1a}')
    html_parts.append('.badge-noclick{background:#3a1a1a;color:#f44336;border:1px solid #5a2a2a}')
    html_parts.append('.meme-cats{display:flex;flex-wrap:wrap;gap:3px}')
    html_parts.append('.tag{font-size:0.58em;padding:2px 5px;background:#1a2a3a;border-radius:8px;color:#5bc0de}')
    html_parts.append('.meme-desc{font-size:0.72em;color:#aaa;line-height:1.35;max-height:80px;overflow-y:auto;padding-right:4px}')
    html_parts.append('.meme-ideas{font-size:0.65em;color:#777;margin-top:4px}')
    html_parts.append('.meme-ideas summary{cursor:pointer;color:#5bc0de}')
    html_parts.append('.meme-ideas li{margin:2px 0 2px 12px}')
    html_parts.append('.meme-actions{margin-top:auto;display:flex;gap:6px;flex-wrap:wrap}')
    html_parts.append('.btn-skip{padding:6px 10px;border:1px solid #ff9800;background:transparent;color:#ff9800;border-radius:6px;cursor:pointer;font-size:0.7em}')
    html_parts.append('.btn-skip:hover{background:#2a1a00}')
    html_parts.append('.btn-regen{padding:6px 10px;border:1px solid #2196F3;background:transparent;color:#2196F3;border-radius:6px;cursor:pointer;font-size:0.7em}')
    html_parts.append('.btn-regen:hover{background:#0a1a2a}')
    # Right panel (clips)
    html_parts.append('.meme-right{flex:1;display:flex;flex-direction:column;gap:8px;min-width:0}')
    html_parts.append('.matches-title{font-size:0.8em;font-weight:bold;color:#00d4aa;display:flex;align-items:center;gap:8px}')
    html_parts.append('.matches-grid{display:flex;flex-direction:column;gap:8px}')
    html_parts.append('.match-option{background:#0a0a18;border:1px solid #1a1a2a;border-radius:8px;padding:10px;transition:all 0.2s;position:relative}')
    html_parts.append('.match-option:hover{border-color:#333}')
    html_parts.append('.match-option.selected{border-color:#4CAF50;background:#0a1a0a;box-shadow:0 0 12px rgba(76,175,80,0.15)}')
    html_parts.append('.opt-header{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}')
    html_parts.append('.score{padding:3px 8px;border-radius:10px;font-size:0.72em;font-weight:bold}')
    html_parts.append('.score-high{background:#4CAF50;color:white}')
    html_parts.append('.score-mid{background:#ff9800;color:white}')
    html_parts.append('.score-low{background:#f44336;color:white}')
    html_parts.append('.clip-mood{font-size:0.65em;color:#888;background:#1a1a2a;padding:2px 6px;border-radius:8px}')
    html_parts.append('.clip-intensidad{font-size:0.6em;color:#666}')
    html_parts.append('.clip-desc{font-size:0.68em;color:#aaa;font-style:italic}')
    html_parts.append('.clip-preview{width:100%;max-height:160px;object-fit:contain;background:#000;border-radius:6px;cursor:pointer;margin:4px 0}')
    html_parts.append('.opt-razon{font-size:0.68em;color:#666;margin:4px 0;padding:4px 8px;background:#0f0f1a;border-radius:4px;border-left:2px solid #333}')
    html_parts.append('.captions-row{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}')
    html_parts.append('.cap-btn{padding:5px 10px;border:1px solid #2a2a3a;background:#1a1a2e;color:#ddd;border-radius:16px;cursor:pointer;font-size:0.7em;transition:all 0.15s}')
    html_parts.append('.cap-btn:hover{border-color:#00d4aa;background:#0a2a2a}')
    html_parts.append('.cap-btn.picked{background:#00d4aa;color:#000;border-color:#00d4aa;font-weight:600}')
    html_parts.append('.cap-none{color:#666;font-style:italic}')
    html_parts.append('.cap-custom{border-style:dashed;color:#5bc0de}')
    html_parts.append('.btn-select{padding:7px 14px;border:none;background:#2196F3;color:white;border-radius:6px;cursor:pointer;font-size:0.72em;font-weight:bold;margin-top:4px;transition:all 0.15s}')
    html_parts.append('.btn-select:hover{background:#1976D2;transform:translateY(-1px)}')
    # YouTube section
    html_parts.append('.yt-section{margin-top:8px;padding:8px 10px;background:#1a1a0a;border-radius:6px;border:1px solid #2a2a1a}')
    html_parts.append('.yt-section b{font-size:0.75em;color:#ff9800}')
    html_parts.append('.yt-section ul{margin:4px 0 0 14px;font-size:0.7em}')
    html_parts.append('.yt-section a{color:#2196F3;text-decoration:none}')
    html_parts.append('.yt-section a:hover{text-decoration:underline}')
    # Zoom overlay
    html_parts.append('#zoom-overlay{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);display:none;align-items:center;justify-content:center;z-index:200;cursor:pointer}')
    html_parts.append('#zoom-overlay img{max-width:90%;max-height:90%;object-fit:contain;border-radius:8px}')
    # Progress bar
    html_parts.append('#progress{position:fixed;top:0;left:0;width:100%;height:3px;background:#1a1a2a;z-index:100}')
    html_parts.append('#progress-bar{height:100%;background:linear-gradient(90deg,#00d4aa,#4CAF50);width:0%;transition:width 0.3s}')
    # Counter
    html_parts.append('#counter{position:fixed;bottom:16px;right:16px;background:#12122a;padding:10px 14px;border-radius:10px;font-size:0.75em;border:1px solid #222;box-shadow:0 4px 12px rgba(0,0,0,0.4)}')
    html_parts.append('#counter b{color:#00d4aa}')
    # Custom caption input
    html_parts.append('.custom-cap-row{display:flex;gap:4px;margin-top:4px}')
    html_parts.append('.custom-cap-input{flex:1;padding:5px 8px;border:1px solid #333;background:#0a0a18;color:#eee;border-radius:6px;font-size:0.7em}')
    html_parts.append('.custom-cap-input:focus{border-color:#00d4aa;outline:none}')
    html_parts.append('.custom-cap-ok{padding:5px 10px;border:none;background:#00d4aa;color:#000;border-radius:6px;cursor:pointer;font-size:0.7em;font-weight:bold}')
    html_parts.append('</style></head><body>')
    
    # Progress bar
    html_parts.append('<div id="progress"><div id="progress-bar"></div></div>')
    
    # Header
    html_parts.append('<div class="hdr"><h1>Match Meme \u2194 Clip</h1>')
    html_parts.append('<div class="stats">')
    html_parts.append('<span class="stat-pill pill-green">&#9989; ' + str(auto_count) + ' auto-aceptados</span>')
    html_parts.append('<span class="stat-pill pill-orange">&#9995; ' + str(review_count) + ' por revisar</span>')
    if no_match_count > 0:
        html_parts.append('<span class="stat-pill pill-red">&#10060; ' + str(no_match_count) + ' sin clip</span>')
    html_parts.append('</div></div>')
    
    # Filters
    html_parts.append('<div class="filters">')
    html_parts.append('<button class="active" onclick="filterCards(\'all\')">Todos (' + str(total) + ')</button>')
    html_parts.append('<button onclick="filterCards(\'por_generar\')">Auto-aceptados (' + str(auto_count) + ')</button>')
    html_parts.append('<button onclick="filterCards(\'match_review\')">Por revisar (' + str(review_count) + ')</button>')
    if no_match_count > 0:
        html_parts.append('<button onclick="filterCards(\'buscar_clip\')">Sin clip (' + str(no_match_count) + ')</button>')
    html_parts.append('<button onclick="filterCards(\'decided\')">Decididos</button>')
    html_parts.append('<button onclick="filterCards(\'pending\')">Sin decidir</button>')
    html_parts.append('</div>')
    
    # Toolbar
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveDecisions()">&#128190; GUARDAR DECISIONES</button>')
    html_parts.append('<button onclick="acceptAllAuto()">&#9989; Confirmar todos los auto-aceptados</button>')
    html_parts.append('<button onclick="collapseDecided()">&#128065; Ocultar decididos</button>')
    html_parts.append('</div>')
    
    # Meme cards
    for idx, meme in enumerate(memes_data):
        sc = meme['shortcode']
        status = meme['status']
        cats_html = ''.join(['<span class="tag">' + t + '</span>' for t in meme['categorias'][:6]])
        
        badge_class = 'badge-auto' if status == 'por_generar' else 'badge-review' if status == 'match_review' else 'badge-noclick'
        badge_text = 'AUTO \u2265 90%' if status == 'por_generar' else 'REVISAR' if status == 'match_review' else 'SIN CLIP'
        
        card_class = 'meme-card'
        if status == 'por_generar':
            card_class += ' auto-accepted'
        
        # Match options
        options_html = ''
        for mi, m in enumerate(meme['matches']):
            score = m['score']
            score_class = 'score-high' if score >= 90 else 'score-mid' if score >= 40 else 'score-low'
            
            # Captions as clickable pills
            captions_btns = ''
            for ci, cap in enumerate(m['captions']):
                cap_safe = cap.replace("'", "\\'")
                captions_btns += '<button class="cap-btn" onclick="pickCaption(\'' + sc + '\',\'' + m['clip_id'] + '\',\'' + cap_safe + '\',this)">' + cap + '</button>'
            captions_btns += '<button class="cap-btn cap-none" onclick="pickCaption(\'' + sc + '\',\'' + m['clip_id'] + '\',\'\',this)">Sin caption</button>'
            captions_btns += '<button class="cap-btn cap-custom" onclick="showCustomCaption(\'' + sc + '\',\'' + m['clip_id'] + '\',this)">&#9999;&#65039; Escribir...</button>'
            
            video_tag = ''
            if m['clip_file']:
                video_tag = '<video class="clip-preview" src="' + m['clip_file'] + '" preload="metadata" onclick="this.paused?this.play():this.pause()" loop muted></video>'
            
            options_html += '<div class="match-option" data-sc="' + sc + '" data-clip="' + m['clip_id'] + '">'
            options_html += '<div class="opt-header">'
            options_html += '<span class="score ' + score_class + '">' + str(int(score)) + '%</span>'
            options_html += '<span class="clip-mood">' + m['clip_mood'] + '</span>'
            options_html += '<span class="clip-intensidad">' + str(m['clip_intensidad']) + '/10</span>'
            options_html += '<span class="clip-desc">' + m['clip_desc'][:50] + '</span>'
            options_html += '</div>'
            options_html += video_tag
            if m['razon']:
                options_html += '<div class="opt-razon">' + m['razon'][:120] + '</div>'
            options_html += '<div class="captions-row">' + captions_btns + '</div>'
            options_html += '<div class="custom-cap-row" style="display:none" id="ccap-' + sc + '-' + str(mi) + '">'
            options_html += '<input class="custom-cap-input" placeholder="Escribe tu caption..." maxlength="50">'
            options_html += '<button class="custom-cap-ok" onclick="submitCustomCaption(\'' + sc + '\',\'' + m['clip_id'] + '\',this)">OK</button>'
            options_html += '</div>'
            options_html += '<button class="btn-select" onclick="selectMatch(\'' + sc + '\',\'' + m['clip_id'] + '\')">&#9989; ELEGIR ESTE CLIP</button>'
            options_html += '</div>'
        
        # YouTube suggestions
        yt_html = ''
        if meme['youtube_sugs']:
            yt_items = ''.join(['<li><a href="https://www.youtube.com/results?search_query=' + s.replace(' ', '+') + '" target="_blank">' + s + '</a></li>' for s in meme['youtube_sugs']])
            yt_html = '<div class="yt-section"><b>&#128269; Buscar clips en YouTube:</b><ul>' + yt_items + '</ul></div>'
        
        # Image
        img_html = '<div class="no-img">Sin imagen</div>'
        if meme['image_file']:
            img_html = '<img class="meme-img" src="' + meme['image_file'] + '" onclick="zoomImg(this.src)" loading="lazy">'
        
        # Ideas collapsible
        ideas_html = ''
        if meme['ideas']:
            ideas_items = ''.join(['<li>' + idea[:80] + '</li>' for idea in meme['ideas'][:3]])
            ideas_html = '<details class="meme-ideas"><summary>Ideas video (' + str(len(meme['ideas'])) + ')</summary><ul>' + ideas_items + '</ul></details>'
        
        # Build card
        html_parts.append('<div class="' + card_class + '" id="mc-' + sc + '" data-sc="' + sc + '" data-status="' + status + '">')
        html_parts.append('<div class="meme-left">')
        html_parts.append(img_html)
        html_parts.append('<div class="meme-meta">')
        html_parts.append('<span class="sc">' + sc + '</span>')
        html_parts.append('<span class="badge ' + badge_class + '">' + badge_text + '</span>')
        html_parts.append('</div>')
        html_parts.append('<div class="meme-cats">' + cats_html + '</div>')
        html_parts.append('<div class="meme-desc">' + meme['descripcion'][:200] + '</div>')
        html_parts.append(ideas_html)
        html_parts.append('<div class="meme-actions">')
        html_parts.append('<button class="btn-skip" onclick="skipMeme(\'' + sc + '\')">&#9197; SKIP</button>')
        html_parts.append('<button class="btn-regen" onclick="alert(\'Corre: python 4_match_clip.py --shortcode ' + sc + ' --force\')">&#128260; Re-matchear</button>')
        html_parts.append('</div>')
        html_parts.append('</div>')
        html_parts.append('<div class="meme-right">')
        html_parts.append('<div class="matches-title">Clips sugeridos (' + str(len(meme['matches'])) + ')</div>')
        html_parts.append('<div class="matches-grid">' + options_html + '</div>')
        html_parts.append(yt_html)
        html_parts.append('</div>')
        html_parts.append('</div>')
    
    # Zoom overlay
    html_parts.append('<div id="zoom-overlay" onclick="this.style.display=\'none\'"><img id="zoom-img"></div>')
    
    # Counter
    html_parts.append('<div id="counter">Decididos: <b><span id="cnt">0</span> / ' + str(total) + '</b></div>')
    
    # JavaScript
    html_parts.append('<script>')
    html_parts.append('var decisions={};')
    html_parts.append('var total=' + str(total) + ';')
    html_parts.append('')
    html_parts.append('function selectMatch(sc,clipId){')
    html_parts.append('  if(!decisions[sc])decisions[sc]={};')
    html_parts.append('  decisions[sc].clip_id=clipId;')
    html_parts.append('  decisions[sc].action="match";')
    html_parts.append('  if(!decisions[sc].caption)decisions[sc].caption="";')
    html_parts.append('  var card=document.getElementById("mc-"+sc);')
    html_parts.append('  card.querySelectorAll(".match-option").forEach(function(o){')
    html_parts.append('    o.classList.toggle("selected",o.dataset.clip===clipId);')
    html_parts.append('  });')
    html_parts.append('  card.classList.add("decided");card.classList.remove("skipped");')
    html_parts.append('  updCnt();')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function pickCaption(sc,clipId,cap,btn){')
    html_parts.append('  if(!decisions[sc])decisions[sc]={};')
    html_parts.append('  decisions[sc].clip_id=clipId;')
    html_parts.append('  decisions[sc].caption=cap;')
    html_parts.append('  decisions[sc].action="match";')
    html_parts.append('  var card=document.getElementById("mc-"+sc);')
    html_parts.append('  card.querySelectorAll(".match-option").forEach(function(o){')
    html_parts.append('    o.classList.toggle("selected",o.dataset.clip===clipId);')
    html_parts.append('  });')
    html_parts.append('  card.querySelectorAll(".cap-btn").forEach(function(b){b.classList.remove("picked");});')
    html_parts.append('  btn.classList.add("picked");')
    html_parts.append('  card.classList.add("decided");card.classList.remove("skipped");')
    html_parts.append('  updCnt();')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function showCustomCaption(sc,clipId,btn){')
    html_parts.append('  var opt=btn.closest(".match-option");')
    html_parts.append('  var row=opt.querySelector(".custom-cap-row");')
    html_parts.append('  row.style.display=row.style.display==="none"?"flex":"none";')
    html_parts.append('  if(row.style.display==="flex")row.querySelector("input").focus();')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function submitCustomCaption(sc,clipId,btn){')
    html_parts.append('  var input=btn.previousElementSibling;')
    html_parts.append('  var cap=input.value.trim();')
    html_parts.append('  if(!cap){alert("Escribe algo");return;}')
    html_parts.append('  if(!decisions[sc])decisions[sc]={};')
    html_parts.append('  decisions[sc].clip_id=clipId;')
    html_parts.append('  decisions[sc].caption=cap;')
    html_parts.append('  decisions[sc].action="match";')
    html_parts.append('  decisions[sc].custom_caption=true;')
    html_parts.append('  var card=document.getElementById("mc-"+sc);')
    html_parts.append('  card.querySelectorAll(".match-option").forEach(function(o){')
    html_parts.append('    o.classList.toggle("selected",o.dataset.clip===clipId);')
    html_parts.append('  });')
    html_parts.append('  card.querySelectorAll(".cap-btn").forEach(function(b){b.classList.remove("picked");});')
    html_parts.append('  card.classList.add("decided");card.classList.remove("skipped");')
    html_parts.append('  input.parentElement.style.display="none";')
    html_parts.append('  alert("Caption guardado: "+cap);')
    html_parts.append('  updCnt();')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function skipMeme(sc){')
    html_parts.append('  decisions[sc]={action:"skip"};')
    html_parts.append('  var card=document.getElementById("mc-"+sc);')
    html_parts.append('  card.classList.add("skipped");card.classList.remove("decided");')
    html_parts.append('  card.querySelectorAll(".match-option").forEach(function(o){o.classList.remove("selected");});')
    html_parts.append('  updCnt();')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function acceptAllAuto(){')
    html_parts.append('  document.querySelectorAll(".meme-card.auto-accepted").forEach(function(card){')
    html_parts.append('    var sc=card.dataset.sc;')
    html_parts.append('    if(decisions[sc])return;')
    html_parts.append('    var firstOpt=card.querySelector(".match-option");')
    html_parts.append('    if(!firstOpt)return;')
    html_parts.append('    var clipId=firstOpt.dataset.clip;')
    html_parts.append('    var firstCap=firstOpt.querySelector(".cap-btn");')
    html_parts.append('    var cap=firstCap?firstCap.textContent:"";')
    html_parts.append('    if(cap==="Sin caption"||cap.includes("Escribir"))cap="";')
    html_parts.append('    decisions[sc]={action:"match",clip_id:clipId,caption:cap};')
    html_parts.append('    firstOpt.classList.add("selected");')
    html_parts.append('    if(firstCap)firstCap.classList.add("picked");')
    html_parts.append('    card.classList.add("decided");')
    html_parts.append('  });')
    html_parts.append('  updCnt();')
    html_parts.append('  alert("Auto-aceptados confirmados!");')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function collapseDecided(){')
    html_parts.append('  document.querySelectorAll(".meme-card.decided,.meme-card.skipped").forEach(function(c){')
    html_parts.append('    c.style.display=c.style.display==="none"?"flex":"none";')
    html_parts.append('  });')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function filterCards(filter){')
    html_parts.append('  document.querySelectorAll(".filters button").forEach(function(b){b.classList.remove("active");});')
    html_parts.append('  event.target.classList.add("active");')
    html_parts.append('  document.querySelectorAll(".meme-card").forEach(function(c){')
    html_parts.append('    var show=true;')
    html_parts.append('    if(filter==="decided")show=c.classList.contains("decided")||c.classList.contains("skipped");')
    html_parts.append('    else if(filter==="pending")show=!c.classList.contains("decided")&&!c.classList.contains("skipped");')
    html_parts.append('    else if(filter!=="all")show=c.dataset.status===filter;')
    html_parts.append('    c.style.display=show?"flex":"none";')
    html_parts.append('  });')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function zoomImg(src){document.getElementById("zoom-img").src=src;document.getElementById("zoom-overlay").style.display="flex";}')
    html_parts.append('')
    html_parts.append('function updCnt(){')
    html_parts.append('  var c=Object.keys(decisions).length;')
    html_parts.append('  document.getElementById("cnt").textContent=c;')
    html_parts.append('  document.getElementById("progress-bar").style.width=(c/total*100)+"%";')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('function saveDecisions(){')
    html_parts.append('  var t=Object.keys(decisions).length;')
    html_parts.append('  if(t===0){alert("No has tomado ninguna decision.");return;}')
    html_parts.append('  var data={timestamp:new Date().toISOString(),total_decisions:t,total_memes:total,decisions:decisions};')
    html_parts.append('  var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('  var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('  a.href=url;a.download="match_results.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('  alert("Guardado: "+t+" decisiones.\\n\\nSiguiente paso:\\npython catalogo_matches.py --apply");')
    html_parts.append('}')
    html_parts.append('')
    html_parts.append('// Keyboard: Escape closes zoom')
    html_parts.append('document.addEventListener("keydown",function(e){')
    html_parts.append('  if(e.key==="Escape")document.getElementById("zoom-overlay").style.display="none";')
    html_parts.append('});')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


def apply_results(results_path=None):
    """Aplica las decisiones del usuario."""
    log = get_logger()
    path = Path(results_path) if results_path else SCRIPT_DIR / "match_results.json"
    downloads_path = Path.home() / "Downloads" / "match_results.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
    else:
        log.error("No se encontro match_results.json")
        log.info("  Buscado en:")
        log.info(f"    {SCRIPT_DIR / 'match_results.json'}")
        log.info(f"    {downloads_path}")
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
            is_custom = decision.get('custom_caption', False)
            
            # Update match as confirmed
            db.execute("""
                UPDATE matches SET match_type = 'confirmed', caption = ?
                WHERE shortcode = ? AND clip_id = ?
            """, (caption, shortcode, clip_id))
            
            # Update meme status
            db.execute("UPDATE memes SET status = 'por_generar' WHERE shortcode = ?", (shortcode,))
            
            # Save to user_feedback
            db.execute("DELETE FROM user_feedback WHERE shortcode = ? AND step = 'match_decision'", (shortcode,))
            db.execute("""
                INSERT INTO user_feedback (shortcode, step, user_said, decision)
                VALUES (?, 'match_decision', ?, ?)
            """, (
                shortcode,
                json.dumps({'clip_id': clip_id, 'caption': caption, 'custom': is_custom}, ensure_ascii=False),
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
    log.info(f"{'='*55}")
    log.info(f"   MATCHES APLICADOS")
    log.info(f"{'='*55}")
    log.info(f"   Confirmados: {matched}")
    log.info(f"   Skipped:     {skipped}")
    log.info(f"{'='*55}")
    
    if matched > 0:
        log.info(f"   {matched} memes listos para generar video.")
        log.info(f"   Siguiente: python 7_generate_video.py")
    
    # Clean up the JSON
    if path.exists():
        path.unlink()
        log.info(f"   Archivo {path.name} eliminado.")


def export_decisions():
    """Exporta todas las decisiones para analisis futuro."""
    log = get_logger()
    db = get_db()
    
    rows = db.execute("""
        SELECT uf.shortcode, uf.step, uf.user_said, uf.decision, uf.created_at,
               c.categorias, c.descripcion,
               m.accuracy as match_score, m.clip_id
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
            'clip_id': row['clip_id'],
            'meme_categorias': row['categorias'],
            'meme_descripcion': row['descripcion'],
            'match_score': row['match_score'],
            'timestamp': row['created_at'],
        })
    
    export_path = SCRIPT_DIR / f"match_decisions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    export_path.write_text(json.dumps(export_data, indent=2, ensure_ascii=False), encoding='utf-8')
    
    log.info(f"Exportado: {export_path.name}")
    log.info(f"Total decisiones: {len(rows)}")


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
    log.info(f"   Auto-aceptados: {sum(1 for m in memes_data if m['status'] == 'por_generar')}")
    log.info(f"   Por revisar: {sum(1 for m in memes_data if m['status'] == 'match_review')}")
    log.info(f"")
    log.info(f"   Acciones disponibles:")
    log.info(f"     - Click en caption = seleccionar")
    log.info(f"     - 'Escribir...' = caption custom")
    log.info(f"     - 'ELEGIR ESTE CLIP' = confirmar sin caption")
    log.info(f"     - 'SKIP' = saltar meme")
    log.info(f"     - 'Confirmar auto-aceptados' = acepta todos los >= 90%")
    log.info(f"     - Filtros arriba para ver solo los que quieras")
    log.info(f"")
    log.info(f"   Al terminar: GUARDAR DECISIONES -> python catalogo_matches.py --apply")
    log.info(f"   Presiona Ctrl+C para cerrar")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Cerrando...")
        server.shutdown()


if __name__ == "__main__":
    main()
