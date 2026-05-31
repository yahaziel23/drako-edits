#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Tutorial Interactivo

Interfaz HTML con guia paso a paso del pipeline completo.
Cada paso tiene descripcion, comandos copiables, y tips.

Uso:
    python tutorial.py

Puerto: 8780
"""

import sys
import os
import time
import webbrowser
import http.server
import threading
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SERVER_PORT = 8780


def get_status_counts():
    """Lee status actual del pipeline para mostrar en tutorial."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from utils.db import init_db, get_db
        init_db()
        db = get_db()
        counts = {}
        rows = db.execute("SELECT status, COUNT(*) as cnt FROM memes GROUP BY status").fetchall()
        for r in rows:
            counts[r['status']] = r['cnt']
        total_clips = db.execute("SELECT COUNT(*) as cnt FROM clips").fetchone()['cnt']
        counts['_total_clips'] = total_clips
        counts['_total_memes'] = sum(counts.get(s, 0) for s in ['por_descargar','descargado','pendiente_review','listo_clasificar','pendiente_match','match_review','por_generar','generado','por_subir','subido','rechazado','descartado_ia'])
        vids = db.execute("SELECT COUNT(*) as cnt FROM videos_generados").fetchone()['cnt']
        counts['_videos'] = vids
        uploaded = db.execute("SELECT COUNT(*) as cnt FROM uploads WHERE status='subido'").fetchone()['cnt']
        counts['_uploaded'] = uploaded
        return counts
    except Exception:
        return {}


def generate_html():
    """Genera el HTML del tutorial."""
    counts = get_status_counts()
    
    def badge(count, label='pendientes'):
        if count and count > 0:
            return f'<span class="badge">{count} {label}</span>'
        return '<span class="badge done">0</span>'
    
    h = []
    h.append('<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">')
    h.append('<title>Meme Reaction V2 - Tutorial</title>')
    h.append('<style>')
    h.append('*{margin:0;padding:0;box-sizing:border-box}')
    h.append('body{font-family:system-ui,-apple-system,sans-serif;background:#08080f;color:#e0e0e0;padding:24px 32px;line-height:1.5}')
    h.append('::-webkit-scrollbar{width:8px}::-webkit-scrollbar-track{background:#111}::-webkit-scrollbar-thumb{background:#333;border-radius:4px}')
    h.append('.container{max-width:1100px;margin:0 auto}')
    h.append('.header{text-align:center;padding:24px;background:linear-gradient(135deg,#0d0d1a,#1a1a3a);border-radius:16px;margin-bottom:24px;border:1px solid #222}')
    h.append('.header h1{font-size:1.6em;margin-bottom:6px;background:linear-gradient(90deg,#ff4444,#ff8800);-webkit-background-clip:text;-webkit-text-fill-color:transparent}')
    h.append('.header p{color:#888;font-size:0.85em}')
    h.append('.stats{display:flex;justify-content:center;gap:16px;margin-top:12px;flex-wrap:wrap}')
    h.append('.stat{background:#111;padding:8px 14px;border-radius:8px;font-size:0.75em;border:1px solid #222}')
    h.append('.stat b{color:#ff6644}')
    h.append('.phase{margin-bottom:20px}')
    h.append('.phase-title{font-size:1em;font-weight:700;padding:10px 16px;background:#12122a;border-radius:10px 10px 0 0;border:1px solid #1a1a3a;border-bottom:none;display:flex;align-items:center;gap:8px}')
    h.append('.phase-title .num{background:#ff4444;color:#fff;width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:0.7em;font-weight:bold}')
    h.append('.steps{border:1px solid #1a1a3a;border-radius:0 0 10px 10px;overflow:hidden}')
    h.append('.step{padding:14px 18px;border-bottom:1px solid #111;display:flex;gap:14px;align-items:flex-start;transition:background 0.15s}')
    h.append('.step:hover{background:#0d0d1a}')
    h.append('.step:last-child{border-bottom:none}')
    h.append('.step-icon{font-size:1.2em;min-width:28px;text-align:center;padding-top:2px}')
    h.append('.step-body{flex:1}')
    h.append('.step-name{font-weight:600;font-size:0.85em;margin-bottom:3px}')
    h.append('.step-desc{font-size:0.72em;color:#999;margin-bottom:8px}')
    h.append('.cmd-row{display:flex;gap:6px;align-items:center;margin-bottom:4px}')
    h.append('.cmd{background:#0a0a18;border:1px solid #222;padding:5px 10px;border-radius:6px;font-family:"JetBrains Mono","Fira Code",monospace;font-size:0.72em;color:#4fc3f7;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}')
    h.append('.copy-btn{padding:4px 10px;background:#222;border:1px solid #333;color:#aaa;border-radius:5px;cursor:pointer;font-size:0.65em;transition:all 0.15s;white-space:nowrap}')
    h.append('.copy-btn:hover{background:#333;color:#fff}')
    h.append('.copy-btn.copied{background:#4CAF50;color:#fff;border-color:#4CAF50}')
    h.append('.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.6em;background:#ff444433;color:#ff6644;font-weight:600;margin-left:8px}')
    h.append('.badge.done{background:#4CAF5033;color:#4CAF50}')
    h.append('.tip{font-size:0.65em;color:#666;margin-top:4px;padding-left:12px;border-left:2px solid #222}')
    h.append('.flags{margin-top:6px}')
    h.append('.flag{display:inline-block;padding:2px 6px;background:#1a1a2e;border:1px solid #222;border-radius:4px;font-size:0.6em;color:#888;margin-right:4px;margin-bottom:3px}')
    h.append('.flag code{color:#ff8800}')
    h.append('.divider{height:1px;background:#1a1a2a;margin:6px 0}')
    h.append('.nav{position:fixed;top:16px;right:16px;display:flex;flex-direction:column;gap:4px;z-index:100}')
    h.append('.nav a{padding:5px 10px;background:#12122a;border:1px solid #222;border-radius:6px;color:#888;text-decoration:none;font-size:0.6em;transition:all 0.15s}')
    h.append('.nav a:hover{color:#fff;border-color:#ff4444}')
    h.append('</style></head><body>')
    
    h.append('<div class="container">')
    
    # Header
    h.append('<div class="header">')
    h.append('<h1>Meme Reaction V2</h1>')
    h.append('<p>Tutorial interactivo del pipeline completo. Copia y pega los comandos.</p>')
    h.append('<div class="stats">')
    h.append(f'<div class="stat">Memes: <b>{counts.get("_total_memes", "?")}</b></div>')
    h.append(f'<div class="stat">Clips: <b>{counts.get("_total_clips", "?")}</b></div>')
    h.append(f'<div class="stat">Videos: <b>{counts.get("_videos", "?")}</b></div>')
    h.append(f'<div class="stat">Subidos: <b>{counts.get("_uploaded", "?")}</b></div>')
    h.append('</div></div>')
    
    # Navigation
    h.append('<div class="nav">')
    h.append('<a href="#phase1">1. Scrape</a>')
    h.append('<a href="#phase2">2. Clasificar</a>')
    h.append('<a href="#phase3">3. Clips</a>')
    h.append('<a href="#phase4">4. Match</a>')
    h.append('<a href="#phase5">5. Video</a>')
    h.append('<a href="#phase6">6. Upload</a>')
    h.append('<a href="#utils">Utils</a>')
    h.append('</div>')
    
    # ========== PHASE 1: SCRAPE + DOWNLOAD ==========
    h.append('<div class="phase" id="phase1">')
    h.append('<div class="phase-title"><span class="num">1</span> Scrape + Descarga de Memes</div>')
    h.append('<div class="steps">')
    
    # 1a
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128270;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Scrape Inicial (perfil nuevo)</div>')
    h.append('<div class="step-desc">Primera vez que agregas un perfil. Scrapea TODOS los posts del grid. Requiere login manual en Brave.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 1a_scrape_inicial.py --perfil nombre_perfil --scrolls 30</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Pausa para login. Ajusta --scrolls segun que tan atras quieras ir.</div>')
    h.append('</div></div>')
    
    # 1b
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128257;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Scrape Nuevos (rutinario)' + badge(counts.get('por_descargar', 0)) + '</div>')
    h.append('<div class="step-desc">Revisa posts recientes de TODOS los perfiles en config.json. Solo guarda los nuevos.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 1b_scrape_nuevos.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Ejecutar cada 1-2 dias para mantener el pipeline alimentado.</div>')
    h.append('</div></div>')
    
    # 2
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#11015;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Descargar Memes' + badge(counts.get('por_descargar', 0)) + '</div>')
    h.append('<div class="step-desc">Descarga imagenes/videos de los posts scrapeados. Fotos van directo a clasificar, frames van a review.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 2_download_memes.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--max 50</code> limitar cantidad</span></div>')
    h.append('</div></div>')
    
    # 2b
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#127912;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Preprocesar (extraer frames)</div>')
    h.append('<div class="step-desc">Extrae el mejor frame de videos descargados. Los marca como pendiente_review.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 2b_preprocess.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('</div></div>')
    
    # batch_review
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128065;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Batch Review (frames)' + badge(counts.get('pendiente_review', 0)) + '</div>')
    h.append('<div class="step-desc">Grid visual de frames extraidos. Aprueba/rechaza con un click. Los aprobados pasan a clasificar.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python batch_review.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="cmd-row"><div class="cmd">python batch_review.py --apply</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Primero revisar en navegador, luego --apply para guardar decisiones.</div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end phase 1
    
    # ========== PHASE 2: CLASIFICAR ==========
    h.append('<div class="phase" id="phase2">')
    h.append('<div class="phase-title"><span class="num">2</span> Clasificar Memes (IA)</div>')
    h.append('<div class="steps">')
    
    # 3
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#129504;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Clasificar con GPT-4o' + badge(counts.get('listo_clasificar', 0)) + '</div>')
    h.append('<div class="step-desc">GPT-4o analiza la imagen: descripcion, categorias, humor, ideas de video. Cuesta ~$0.01/meme.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 3_classify_meme.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--max 20</code> limitar por sesion</span><span class="flag"><code>--shortcode ABC</code> uno solo</span></div>')
    h.append('<div class="tip">Default: procesa max 20 por sesion (config.json). Fotos validas pasan a pendiente_match.</div>')
    h.append('</div></div>')
    
    # view_clasificados
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128202;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Ver Clasificaciones (QA)</div>')
    h.append('<div class="step-desc">Interfaz para revisar que dijo la IA. Puedes corregir categorias o rechazar memes mal clasificados.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python view_clasificados.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Opcional pero recomendado. Tu feedback mejora los prompts futuros.</div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end phase 2
    
    # ========== PHASE 3: CLIPS ==========
    h.append('<div class="phase" id="phase3">')
    h.append('<div class="phase-title"><span class="num">3</span> Clips de Reaccion</div>')
    h.append('<div class="steps">')
    
    # descargar_clips
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#127916;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Descargar Clip de YouTube</div>')
    h.append('<div class="step-desc">Recorta un segmento de video de YouTube como clip de reaccion. Usa yt-dlp + ffmpeg.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python descargar_clips.py "https://youtube.com/watch?v=VIDEO_ID" --start 5 --end 12</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">--start y --end en segundos. El clip se guarda en clips/ con ID automatico.</div>')
    h.append('</div></div>')
    
    # catalogo_clips
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#9989;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Aprobar Clips (catalogo)</div>')
    h.append('<div class="step-desc">Interfaz para ver clips descargados y aprobarlos para uso en el pipeline.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python catalogo_clips.py --ia</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--ia</code> auto-aprueba con IA</span></div>')
    h.append('</div></div>')
    
    # 3b
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#127991;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Categorizar Clips (Gemini)</div>')
    h.append('<div class="step-desc">Gemini 2.5 Flash analiza cada clip: mood, intensidad, descripcion, categorias. Gratis.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 3b_categorizar_clips.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Solo categoriza clips aprobados sin categorizar. Gemini Flash es gratuito.</div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end phase 3
    
    # ========== PHASE 4: MATCH ==========
    h.append('<div class="phase" id="phase4">')
    h.append('<div class="phase-title"><span class="num">4</span> Match Meme + Clip</div>')
    h.append('<div class="steps">')
    
    # 4_match
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#129520;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Match Automatico (GPT-4o-mini)' + badge(counts.get('pendiente_match', 0)) + '</div>')
    h.append('<div class="step-desc">La IA elige el mejor clip para cada meme. &ge;90% auto-acepta, 40-89% va a review, &lt;40% sin clip.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 4_match_clip.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--shortcode ABC</code> uno solo</span><span class="flag"><code>--max 10</code> limitar</span></div>')
    h.append('</div></div>')
    
    # catalogo_matches
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128203;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Revisar Matches' + badge(counts.get('match_review', 0)) + '</div>')
    h.append('<div class="step-desc">Interfaz para confirmar/rechazar matches. Puedes editar caption, re-matchear, o confirmar auto-aceptados.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python catalogo_matches.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="cmd-row"><div class="cmd">python catalogo_matches.py --apply</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="cmd-row"><div class="cmd">python catalogo_matches.py --confirmed</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--confirmed</code> ver cola de confirmados</span></div>')
    h.append('<div class="tip">Flujo: abrir interfaz &#8594; decidir &#8594; guardar &#8594; --apply para guardar en DB.</div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end phase 4
    
    # ========== PHASE 5: VIDEO ==========
    h.append('<div class="phase" id="phase5">')
    h.append('<div class="phase-title"><span class="num">5</span> Generar Videos</div>')
    h.append('<div class="steps">')
    
    # 7_generate
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#127909;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Generar Videos (ffmpeg)' + badge(counts.get('por_generar', 0)) + '</div>')
    h.append('<div class="step-desc">Arma video vertical 1080x1920: meme arriba (65%), clip abajo (30%), caption en medio. ffmpeg.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 7_generate_video.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--force</code> regenerar todos</span><span class="flag"><code>--shortcode ABC</code> uno solo</span><span class="flag"><code>--dry-run</code> preview sin generar</span><span class="flag"><code>--caption-size L</code> S/M/L/XL</span></div>')
    h.append('</div></div>')
    
    # preview_videos
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128064;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Preview + Aprobar Videos' + badge(counts.get('generado', 0)) + '</div>')
    h.append('<div class="step-desc">Revisa videos generados. Puedes aprobar, regenerar con otro caption, regresar a match, o descartar.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python preview_videos.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="cmd-row"><div class="cmd">python preview_videos.py --apply</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">APROBAR &#8594; por_subir | REGENERAR &#8594; edita caption | REGRESAR &#8594; re-match | DESCARTAR &#8594; fin</div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end phase 5
    
    # ========== PHASE 6: UPLOAD ==========
    h.append('<div class="phase" id="phase6">')
    h.append('<div class="phase-title"><span class="num">6</span> Subir a YouTube</div>')
    h.append('<div class="steps">')
    
    # auth
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128272;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Autenticar YouTube (primera vez)</div>')
    h.append('<div class="step-desc">Abre navegador para autorizar acceso. Solo se hace una vez, guarda token local.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --auth</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Requiere client_secrets.json (Google Cloud Console &#8594; OAuth 2.0 Desktop App).</div>')
    h.append('</div></div>')
    
    # upload con interfaz
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128197;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Generar Metadata + Programar' + badge(counts.get('por_subir', 0)) + '</div>')
    h.append('<div class="step-desc">GPT genera titulo/descripcion/tags. Interfaz para editar y programar hora. Auto-detecta siguiente slot libre (8am/12pm/4pm/7pm/10pm).</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --apply</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --upload</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Flujo: interfaz &#8594; editar metadata &#8594; guardar &#8594; --apply &#8594; --upload</div>')
    h.append('</div></div>')
    
    # full auto
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#9889;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Full Auto (sin interfaz)</div>')
    h.append('<div class="step-desc">Genera metadata + auto-programa en siguiente slot libre + sube. Todo en un comando.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --auto</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="tip">Slots diarios: 8am, 12pm, 4pm, 7pm, 10pm (Mexico City). Detecta cuales estan ocupados.</div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end phase 6
    
    # ========== UTILS ==========
    h.append('<div class="phase" id="utils">')
    h.append('<div class="phase-title"><span class="num">&#9881;</span> Utilidades</div>')
    h.append('<div class="steps">')
    
    # status
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128202;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Ver Status del Pipeline</div>')
    h.append('<div class="step-desc">Resumen completo: cuantos memes en cada paso, clips, videos, budget de API.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python status.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="flags"><span class="flag"><code>--detailed</code> desglose por perfil</span></div>')
    h.append('</div></div>')
    
    # upload status
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#128246;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Status de Uploads</div>')
    h.append('<div class="step-desc">Ver estado de videos subidos/programados/con error.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --status</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('</div></div>')
    
    # generate-meta only
    h.append('<div class="step">')
    h.append('<div class="step-icon">&#129302;</div>')
    h.append('<div class="step-body">')
    h.append('<div class="step-name">Solo Generar Metadata (sin subir)</div>')
    h.append('<div class="step-desc">Genera titulos/descripciones con IA para preview sin subir nada.</div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --generate-meta</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('</div></div>')
    
    h.append('</div></div>')  # end utils
    
    # ========== QUICK REFERENCE ==========
    h.append('<div class="phase" id="quickref">')
    h.append('<div class="phase-title"><span class="num">&#128161;</span> Flujo Rapido (dia a dia)</div>')
    h.append('<div class="steps">')
    h.append('<div class="step">')
    h.append('<div class="step-body" style="padding:8px">')
    h.append('<div class="step-desc" style="font-size:0.78em;color:#bbb">')
    h.append('Si ya tienes perfiles configurados y clips, el flujo diario es:')
    h.append('</div>')
    h.append('<div class="cmd-row" style="margin-top:8px"><div class="cmd">python 1b_scrape_nuevos.py && python 2_download_memes.py && python 3_classify_meme.py && python 4_match_clip.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="step-desc" style="font-size:0.68em;color:#666;margin-top:6px">Scrape &#8594; Download &#8594; Classify &#8594; Match (todo automatico)</div>')
    h.append('<div class="divider"></div>')
    h.append('<div class="cmd-row"><div class="cmd">python catalogo_matches.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="step-desc" style="font-size:0.68em;color:#666">Revisar matches &#8594; confirmar</div>')
    h.append('<div class="divider"></div>')
    h.append('<div class="cmd-row"><div class="cmd">python 7_generate_video.py && python preview_videos.py</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="step-desc" style="font-size:0.68em;color:#666">Generar &#8594; Preview &#8594; Aprobar</div>')
    h.append('<div class="divider"></div>')
    h.append('<div class="cmd-row"><div class="cmd">python 9_upload_social.py --auto</div><button class="copy-btn" onclick="copyCmd(this)">Copiar</button></div>')
    h.append('<div class="step-desc" style="font-size:0.68em;color:#666">Subir con auto-schedule &#9889;</div>')
    h.append('</div></div>')
    h.append('</div></div>')  # end quickref
    
    h.append('</div>')  # end container
    
    # JavaScript
    h.append('<script>')
    h.append('function copyCmd(btn){')
    h.append('  var cmd=btn.previousElementSibling.textContent;')
    h.append('  navigator.clipboard.writeText(cmd).then(function(){')
    h.append('    btn.textContent="Copiado!";btn.classList.add("copied");')
    h.append('    setTimeout(function(){btn.textContent="Copiar";btn.classList.remove("copied");},1500);')
    h.append('  });')
    h.append('}')
    h.append('</script>')
    h.append('</body></html>')
    
    return '\n'.join(h)


def main():
    html = generate_html()
    out_path = SCRIPT_DIR / "tutorial.html"
    out_path.write_text(html, encoding='utf-8')
    
    # Serve
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SERVER_PORT}/tutorial.html"
    webbrowser.open(url)
    
    print(f"")
    print(f"  ==============================")
    print(f"  Tutorial abierto en navegador")
    print(f"  Puerto: {SERVER_PORT}")
    print(f"  {url}")
    print(f"  ==============================")
    print(f"  Ctrl+C para cerrar")
    print(f"")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Cerrando...")
        server.shutdown()


if __name__ == '__main__':
    main()
