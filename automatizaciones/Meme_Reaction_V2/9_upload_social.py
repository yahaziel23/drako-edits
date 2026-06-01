#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Upload Social (YouTube Shorts)

Sube videos a YouTube Shorts con metadata generada por IA.
Soporta scheduling: programar publicacion para fecha/hora especifica.

Flujo:
  1. Lee videos con status='por_subir'
  2. GPT-4o-mini genera titulo + descripcion + tags
  3. Interfaz HTML para revisar/editar metadata + programar fecha
  4. Sube a YouTube como privado con publishAt (publica solo)
  5. Registra en SQLite (tabla uploads)

Requisitos:
    pip install google-api-python-client google-auth-oauthlib openai python-dotenv
    
    YouTube Data API v3 habilitada en Google Cloud Console
    client_secrets.json en la raiz del proyecto (OAuth 2.0 credentials)

Uso:
    python 9_upload_social.py                    # Genera metadata + abre interfaz
    python 9_upload_social.py --generate-meta    # Solo genera metadata (sin subir)
    python 9_upload_social.py --upload           # Sube los que tienen metadata lista
    python 9_upload_social.py --apply            # Aplica decisiones del JSON
    python 9_upload_social.py --status           # Ver estado de uploads
    python 9_upload_social.py --auth             # Solo autenticar con YouTube

Puerto interfaz: 8770
"""

import sys
import os
import json
import argparse
import time
import webbrowser
import http.server
import threading
from pathlib import Path
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR / '.env')

from utils.db import init_db, get_db
from utils.config import load_config
from utils.logger import setup_logger, get_logger

VIDEOS_DIR = SCRIPT_DIR / "videos"
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
CREDENTIALS_FILE = SCRIPT_DIR / "client_secrets.json"
TOKEN_FILE = SCRIPT_DIR / "youtube_token.json"
META_HTML = SCRIPT_DIR / "upload_scheduler.html"
SERVER_PORT = 8770

# YouTube API scopes
YOUTUBE_SCOPES = ['https://www.googleapis.com/auth/youtube.upload', 'https://www.googleapis.com/auth/youtube.readonly']


# ============================================================
# METADATA GENERATION (OpenAI)
# ============================================================

METADATA_PROMPT = """Eres un experto en contenido viral de TikTok/YouTube Shorts.
Genera metadata para un video corto de meme de reaccion.

INFO DEL VIDEO:
- Meme: {meme_desc}
- Categorias: {categorias}
- Caption en el video: "{caption}"
- Clip de reaccion: {clip_desc}
- Duracion: {duration}s

Genera un JSON con:
{{
  "titulo": "Titulo atractivo para YouTube Shorts (max 70 chars, con emoji)",
  "descripcion": "Descripcion corta (2-3 lineas, con hashtags al final)",
  "tags": ["tag1", "tag2", "tag3", "..."],
  "titulo_alternativo": "Otra opcion de titulo"
}}

REGLAS:
- Titulo: gancho emocional, max 70 chars, 1-2 emojis, estilo viral latino
- Descripcion: breve, con CTA ("Sigueme para mas"), hashtags al final (#memes #humor #shorts)
- Tags: 8-12 tags relevantes en espanol (sin #)
- Piensa en SEO de YouTube Shorts: que buscaria alguien para encontrar esto?
- Humor mexicano/latino, lenguaje informal
"""


def generate_metadata_for_video(video_data, api_key):
    """Genera titulo/descripcion/tags con GPT-4o-mini."""
    from openai import OpenAI
    
    client = OpenAI(api_key=api_key)
    
    prompt = METADATA_PROMPT.format(
        meme_desc=video_data.get('meme_desc', '')[:150],
        categorias=', '.join(video_data.get('categorias', [])[:5]),
        caption=video_data.get('caption', ''),
        clip_desc=video_data.get('clip_desc', ''),
        duration=video_data.get('duration', 0)
    )
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.7,
        response_format={"type": "json_object"}
    )
    
    result = json.loads(response.choices[0].message.content.strip())
    return result


# ============================================================
# YOUTUBE AUTH
# ============================================================

def get_youtube_service():
    """Obtiene servicio autenticado de YouTube."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    
    creds = None
    
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), YOUTUBE_SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"No se encontro client_secrets.json\n"
                    f"Descargalo de Google Cloud Console:\n"
                    f"  1. console.cloud.google.com -> APIs & Services -> Credentials\n"
                    f"  2. Create OAuth 2.0 Client ID (Desktop app)\n"
                    f"  3. Download JSON -> rename to client_secrets.json\n"
                    f"  4. Ponlo en: {SCRIPT_DIR}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=8771)
        
        # Save token
        TOKEN_FILE.write_text(creds.to_json(), encoding='utf-8')
    
    return build('youtube', 'v3', credentials=creds)


# ============================================================
# YOUTUBE UPLOAD
# ============================================================

def upload_to_youtube(youtube, video_path, title, description, tags, publish_at=None):
    """
    Sube video a YouTube.
    Si publish_at se proporciona, sube como privado y programa publicacion.
    """
    from googleapiclient.http import MediaFileUpload
    
    # Privacy: private if scheduled, public if immediate
    privacy = 'private' if publish_at else 'public'
    
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '23',  # Comedy
        },
        'status': {
            'privacyStatus': privacy,
            'selfDeclaredMadeForKids': False,
        }
    }
    
    # Schedule publication
    if publish_at:
        body['status']['publishAt'] = publish_at  # ISO 8601: 2026-06-01T10:00:00Z
    
    media = MediaFileUpload(
        str(video_path),
        mimetype='video/mp4',
        resumable=True,
        chunksize=1024*1024*5  # 5MB chunks
    )
    
    request = youtube.videos().insert(
        part='snippet,status',
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
    
    return response


# ============================================================
# DATA QUERIES
# ============================================================

def get_videos_for_upload():
    """Obtiene videos listos para subir."""
    db = get_db()
    
    rows = db.execute("""
        SELECT vg.id as video_id, vg.shortcode, vg.output_path, vg.duracion_s,
               mt.caption, mt.clip_id, mt.accuracy,
               cl.descripcion_corta as clip_desc, cl.mood as clip_mood,
               c.descripcion as meme_desc, c.categorias
        FROM videos_generados vg
        JOIN memes m ON vg.shortcode = m.shortcode
        JOIN matches mt ON vg.match_id = mt.id
        JOIN clips cl ON mt.clip_id = cl.id
        JOIN clasificaciones c ON vg.shortcode = c.shortcode
        WHERE m.status = 'por_subir'
        AND vg.selected = 1
        ORDER BY vg.generated_at
    """).fetchall()
    
    results = []
    for row in rows:
        cats = []
        try:
            cats = json.loads(row['categorias']) if row['categorias'] else []
        except Exception:
            pass
        
        # Check if already has metadata generated
        existing_upload = db.execute("""
            SELECT title, description, hashtags, scheduled_at
            FROM uploads WHERE video_id = ? AND status = 'pendiente'
        """, (row['video_id'],)).fetchone()
        
        video_path = Path(row['output_path'])
        
        results.append({
            'video_id': row['video_id'],
            'shortcode': row['shortcode'],
            'video_file': 'videos/' + video_path.name if video_path.exists() else None,
            'video_path': str(video_path),
            'caption': row['caption'] or '',
            'clip_desc': row['clip_desc'] or '',
            'clip_mood': row['clip_mood'] or '',
            'meme_desc': row['meme_desc'] or '',
            'categorias': cats,
            'duration': row['duracion_s'] or 0,
            # Pre-generated metadata (if exists)
            'title': existing_upload['title'] if existing_upload else None,
            'description': existing_upload['description'] if existing_upload else None,
            'tags': json.loads(existing_upload['hashtags']) if existing_upload and existing_upload['hashtags'] else None,
            'scheduled_at': existing_upload['scheduled_at'] if existing_upload else None,
        })
    
    return results


def ensure_upload_columns():
    """Agrega columnas necesarias a uploads si no existen."""
    db = get_db()
    new_cols = [
        ("scheduled_at", "TIMESTAMP"),
        ("title", "TEXT"),
        ("description", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        try:
            db.execute(f"ALTER TABLE uploads ADD COLUMN {col_name} {col_type}")
            db.commit()
        except Exception:
            pass


# ============================================================
# GENERATE METADATA (batch)
# ============================================================

def generate_all_metadata():
    """Genera metadata para todos los videos pendientes."""
    log = get_logger()
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        log.error("OPENAI_API_KEY no encontrada")
        return
    
    videos = get_videos_for_upload()
    if not videos:
        log.info("No hay videos pendientes de subir.")
        return
    
    db = get_db()
    generated = 0
    
    for v in videos:
        if v['title']:  # Already has metadata
            continue
        
        log.info(f"  Generando metadata: {v['shortcode']}")
        
        try:
            meta = generate_metadata_for_video(v, api_key)
            
            # Save to uploads table
            db.execute("DELETE FROM uploads WHERE video_id = ? AND status = 'pendiente'", (v['video_id'],))
            db.execute("""
                INSERT INTO uploads (video_id, platform, title, description, hashtags, status)
                VALUES (?, 'youtube', ?, ?, ?, 'pendiente')
            """, (
                v['video_id'],
                meta.get('titulo', ''),
                meta.get('descripcion', ''),
                json.dumps(meta.get('tags', []), ensure_ascii=False)
            ))
            db.commit()
            
            log.info(f"    Titulo: {meta.get('titulo', '')[:50]}")
            generated += 1
            time.sleep(1)
            
        except Exception as e:
            log.error(f"    Error: {e}")
    
    log.info(f"  Metadata generada para {generated} videos")



# ============================================================
# AUTO-SCHEDULING (find next available slot)
# ============================================================

DAILY_SLOTS = [8, 12, 16, 19, 22]  # 8am, 12pm, 4pm, 7pm, 10pm (Mexico City)
TIMEZONE = 'America/Mexico_City'


def get_scheduled_videos(youtube):
    """Obtiene videos programados (privados con publishAt en el futuro)."""
    from zoneinfo import ZoneInfo
    
    utc = ZoneInfo('UTC')
    now_utc = datetime.now(utc)
    
    # Search my uploads that are private (scheduled = private + publishAt)
    scheduled_times = []
    
    try:
        # Get my channel's uploads playlist
        channels_response = youtube.channels().list(
            part='contentDetails',
            mine=True
        ).execute()
        
        uploads_playlist = channels_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        # Get recent videos from uploads
        videos_response = youtube.playlistItems().list(
            part='contentDetails',
            playlistId=uploads_playlist,
            maxResults=50
        ).execute()
        
        video_ids = [item['contentDetails']['videoId'] for item in videos_response.get('items', [])]
        
        if not video_ids:
            return scheduled_times
        
        # Get status details for these videos
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i+50]
            details = youtube.videos().list(
                part='status',
                id=','.join(batch)
            ).execute()
            
            for video in details.get('items', []):
                status = video.get('status', {})
                publish_at = status.get('publishAt')
                if publish_at and status.get('privacyStatus') == 'private':
                    # Parse publishAt (ISO 8601)
                    try:
                        dt = datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
                        if dt > now_utc:
                            scheduled_times.append(dt)
                    except Exception:
                        pass
    
    except Exception as e:
        get_logger().warning(f"  No se pudo consultar videos programados: {e}")
    
    return scheduled_times


def find_next_available_slots(youtube, num_slots=5):
    """Encuentra los proximos N slots disponibles segun horarios diarios."""
    from zoneinfo import ZoneInfo
    
    local_tz = ZoneInfo(TIMEZONE)
    utc_tz = ZoneInfo('UTC')
    now_local = datetime.now(local_tz)
    
    # Get already scheduled times
    scheduled_utc = get_scheduled_videos(youtube)
    scheduled_local = [dt.astimezone(local_tz) for dt in scheduled_utc]
    
    # Build set of occupied slots (date + hour)
    occupied = set()
    for dt in scheduled_local:
        occupied.add((dt.date(), dt.hour))
    
    # Find available slots starting from now
    available = []
    check_date = now_local.date()
    max_days_ahead = 30  # Look up to 30 days ahead
    
    for day_offset in range(max_days_ahead):
        current_date = check_date + timedelta(days=day_offset)
        
        for hour in DAILY_SLOTS:
            slot_dt = datetime(current_date.year, current_date.month, current_date.day,
                             hour, 0, 0, tzinfo=local_tz)
            
            # Skip slots in the past
            if slot_dt <= now_local:
                continue
            
            # Skip occupied slots
            if (current_date, hour) in occupied:
                continue
            
            available.append(slot_dt)
            
            if len(available) >= num_slots:
                return available
    
    return available


def auto_assign_schedule(youtube, num_videos):
    """Asigna automaticamente los proximos slots disponibles."""
    log = get_logger()
    from zoneinfo import ZoneInfo
    
    slots = find_next_available_slots(youtube, num_videos)
    
    if not slots:
        log.warning("No se encontraron slots disponibles en los proximos 30 dias")
        return []
    
    log.info(f"  Slots auto-asignados:")
    for i, slot in enumerate(slots):
        log.info(f"    [{i+1}] {slot.strftime('%Y-%m-%d %H:%M')} ({TIMEZONE})")
    
    return slots

# ============================================================
# HTML INTERFACE (Scheduling + Review)
# ============================================================

def generate_scheduler_html(videos):
    """Genera HTML para revisar metadata y programar uploads."""
    total = len(videos)
    
    # Default dates will be passed in (auto-scheduled)
    # Fallback if no auto-schedule
    default_dates = getattr(generate_scheduler_html, '_auto_dates', [])
    if not default_dates:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(TIMEZONE))
        for i in range(total):
            scheduled = now + timedelta(days=1, hours=i*3)
            default_dates.append(scheduled.strftime('%Y-%m-%dT%H:%M'))
    
    html_parts = []
    html_parts.append('<!DOCTYPE html><html><head><meta charset="UTF-8">')
    html_parts.append('<title>Upload Scheduler | ' + str(total) + ' videos</title>')
    html_parts.append('<style>')
    html_parts.append('*{margin:0;padding:0;box-sizing:border-box}')
    html_parts.append('body{font-family:system-ui,sans-serif;background:#0a0a12;color:#eee;padding:16px 24px}')
    html_parts.append('.hdr{text-align:center;margin-bottom:16px;padding:12px;background:linear-gradient(135deg,#12122a,#1a1a3a);border-radius:12px;border:1px solid #222}')
    html_parts.append('.hdr h1{font-size:1.2em}')
    html_parts.append('.tb{display:flex;justify-content:center;gap:8px;margin-bottom:16px}')
    html_parts.append('.tb button{padding:8px 16px;border:1px solid #333;background:#1a1a2e;color:#ddd;border-radius:8px;cursor:pointer;font-size:0.8em}')
    html_parts.append('.tb .sv{background:#ff0000;color:#fff;border-color:#ff0000;font-weight:bold}')
    html_parts.append('.ucard{background:#12122a;border-radius:12px;padding:16px;margin-bottom:14px;border:1px solid #1a1a2a}')
    html_parts.append('.ucard-top{display:flex;gap:16px}')
    html_parts.append('.ucard video{width:200px;max-height:360px;border-radius:8px;background:#000}')
    html_parts.append('.ucard-form{flex:1;display:flex;flex-direction:column;gap:8px}')
    html_parts.append('.field{display:flex;flex-direction:column;gap:3px}')
    html_parts.append('.field label{font-size:0.65em;color:#888;text-transform:uppercase;letter-spacing:0.5px}')
    html_parts.append('.field input,.field textarea,.field select{padding:6px 10px;border:1px solid #333;background:#0a0a18;color:#eee;border-radius:6px;font-size:0.8em;font-family:inherit}')
    html_parts.append('.field textarea{resize:vertical;min-height:60px}')
    html_parts.append('.field input:focus,.field textarea:focus{border-color:#ff4444;outline:none}')
    html_parts.append('.sched-row{display:flex;gap:12px;align-items:flex-end}')
    html_parts.append('.meta-info{font-size:0.65em;color:#666;display:flex;gap:12px;margin-top:4px}')
    html_parts.append('.btn-now{padding:6px 12px;border:none;background:#4CAF50;color:white;border-radius:6px;cursor:pointer;font-size:0.7em}')
    html_parts.append('#counter{position:fixed;bottom:16px;right:16px;background:#12122a;padding:10px 14px;border-radius:10px;font-size:0.75em;border:1px solid #222}')
    html_parts.append('</style></head><body>')
    
    html_parts.append('<div class="hdr"><h1>&#9654; YouTube Shorts - Scheduler</h1>')
    html_parts.append('<div style="font-size:0.75em;color:#888;margin-top:4px">' + str(total) + ' videos por subir</div></div>')
    
    html_parts.append('<div class="tb">')
    html_parts.append('<button class="sv" onclick="saveSchedule()">&#128190; GUARDAR SCHEDULE</button>')
    html_parts.append('<button onclick="uploadNow()">&#9889; Subir AHORA (todos)</button>')
    html_parts.append('</div>')
    
    for idx, v in enumerate(videos):
        vid = str(v['video_id'])
        title = (v['title'] or '').replace('"', '&quot;')
        desc = (v['description'] or '').replace('"', '&quot;')
        tags = ', '.join(v['tags']) if v['tags'] else ''
        sched = v['scheduled_at'] or default_dates[idx] if idx < len(default_dates) else ''
        
        video_tag = ''
        if v['video_file']:
            video_tag = '<video src="' + v['video_file'] + '" controls loop preload="metadata"></video>'
        
        html_parts.append('<div class="ucard" data-vid="' + vid + '">')
        html_parts.append('<div class="ucard-top">')
        html_parts.append(video_tag)
        html_parts.append('<div class="ucard-form">')
        html_parts.append('<div class="field"><label>Titulo</label><input type="text" id="title-' + vid + '" value="' + title + '" maxlength="100"></div>')
        html_parts.append('<div class="field"><label>Descripcion</label><textarea id="desc-' + vid + '">' + (v['description'] or '') + '</textarea></div>')
        html_parts.append('<div class="field"><label>Tags (separados por coma)</label><input type="text" id="tags-' + vid + '" value="' + tags + '"></div>')
        html_parts.append('<div class="sched-row">')
        html_parts.append('<div class="field"><label>Programar publicacion</label><input type="datetime-local" id="sched-' + vid + '" value="' + sched + '"></div>')
        html_parts.append('<button class="btn-now" onclick="document.getElementById(\'sched-' + vid + '\').value=\'\'">Subir ya (sin schedule)</button>')
        html_parts.append('</div>')
        html_parts.append('<div class="meta-info">')
        html_parts.append('<span>Caption: ' + (v['caption'] or 'sin caption')[:30] + '</span>')
        html_parts.append('<span>Mood: ' + v['clip_mood'] + '</span>')
        html_parts.append('<span>' + str(v['duration']) + 's</span>')
        html_parts.append('</div>')
        html_parts.append('</div></div></div>')
    
    html_parts.append('<div id="counter">Videos: <b>' + str(total) + '</b></div>')
    
    # JavaScript
    html_parts.append('<script>')
    html_parts.append('function saveSchedule(){')
    html_parts.append('  var cards=document.querySelectorAll(".ucard");')
    html_parts.append('  var schedule={};')
    html_parts.append('  cards.forEach(function(card){')
    html_parts.append('    var vid=card.dataset.vid;')
    html_parts.append('    schedule[vid]={')
    html_parts.append('      title:document.getElementById("title-"+vid).value,')
    html_parts.append('      description:document.getElementById("desc-"+vid).value,')
    html_parts.append('      tags:document.getElementById("tags-"+vid).value.split(",").map(function(t){return t.trim();}).filter(Boolean),')
    html_parts.append('      scheduled_at:document.getElementById("sched-"+vid).value||null')
    html_parts.append('    };')
    html_parts.append('  });')
    html_parts.append('  var data={timestamp:new Date().toISOString(),videos:schedule};')
    html_parts.append('  var blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});')
    html_parts.append('  var url=URL.createObjectURL(blob);var a=document.createElement("a");')
    html_parts.append('  a.href=url;a.download="upload_schedule.json";a.click();URL.revokeObjectURL(url);')
    html_parts.append('  alert("Schedule guardado!\\n\\nSiguiente:\\npython 9_upload_social.py --apply\\npython 9_upload_social.py --upload");')
    html_parts.append('}')
    html_parts.append('function uploadNow(){')
    html_parts.append('  document.querySelectorAll("input[type=datetime-local]").forEach(function(i){i.value="";});')
    html_parts.append('  alert("Schedule limpiado. Guarda y corre --upload para subir inmediatamente.");')
    html_parts.append('}')
    html_parts.append('</script></body></html>')
    
    return '\n'.join(html_parts)


# ============================================================
# APPLY SCHEDULE
# ============================================================

def apply_schedule(results_path=None):
    """Aplica el schedule del JSON a la DB."""
    log = get_logger()
    path = Path(results_path) if results_path else SCRIPT_DIR / "upload_schedule.json"
    downloads_path = Path.home() / "Downloads" / "upload_schedule.json"
    
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
    elif downloads_path.exists():
        data = json.loads(downloads_path.read_text(encoding='utf-8'))
        path = downloads_path
    else:
        log.error("No se encontro upload_schedule.json")
        return
    
    videos = data.get('videos', {})
    db = get_db()
    updated = 0
    
    for vid, meta in videos.items():
        title = meta.get('title', '')
        description = meta.get('description', '')
        tags = json.dumps(meta.get('tags', []), ensure_ascii=False)
        scheduled_at = meta.get('scheduled_at', None)
        
        # Update or insert in uploads
        db.execute("DELETE FROM uploads WHERE video_id = ? AND status = 'pendiente'", (int(vid),))
        db.execute("""
            INSERT INTO uploads (video_id, platform, title, description, hashtags, scheduled_at, status)
            VALUES (?, 'youtube', ?, ?, ?, ?, 'pendiente')
        """, (int(vid), title, description, tags, scheduled_at))
        updated += 1
    
    db.commit()
    log.info(f"Schedule actualizado: {updated} videos")
    
    if path.exists():
        path.unlink()


# ============================================================
# UPLOAD EXECUTION
# ============================================================

def execute_uploads():
    """Ejecuta uploads programados."""
    log = get_logger()
    db = get_db()
    
    rows = db.execute("""
        SELECT u.id as upload_id, u.video_id, u.title, u.description, u.hashtags, u.scheduled_at,
               vg.output_path, vg.shortcode
        FROM uploads u
        JOIN videos_generados vg ON u.video_id = vg.id
        WHERE u.status = 'pendiente'
        ORDER BY u.scheduled_at NULLS FIRST
    """).fetchall()
    
    if not rows:
        log.info("No hay uploads pendientes.")
        return
    
    # Auth
    log.info("Autenticando con YouTube...")
    try:
        youtube = get_youtube_service()
        log.info("  Autenticado OK")
    except FileNotFoundError as e:
        log.error(str(e))
        return
    except Exception as e:
        log.error(f"Error de autenticacion: {e}")
        return
    
    uploaded = 0
    errors = 0
    
    for row in rows:
        video_path = Path(row['output_path'])
        if not video_path.exists():
            log.error(f"  Video no encontrado: {video_path}")
            errors += 1
            continue
        
        title = row['title'] or f"Meme {row['shortcode']} #shorts"
        description = row['description'] or ''
        tags = []
        try:
            tags = json.loads(row['hashtags']) if row['hashtags'] else []
        except Exception:
            pass
        
        # Convert local time (Mexico City) to UTC for YouTube API
        publish_at = None
        if row['scheduled_at']:
            try:
                from zoneinfo import ZoneInfo
                local_tz = ZoneInfo('America/Mexico_City')
                utc_tz = ZoneInfo('UTC')
                # Parse as naive local time, attach Mexico_City timezone, convert to UTC
                dt = datetime.fromisoformat(row['scheduled_at'])
                dt_local = dt.replace(tzinfo=local_tz)
                dt_utc = dt_local.astimezone(utc_tz)
                publish_at = dt_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')
            except Exception:
                pass
        
        log.info(f"  Subiendo: {row['shortcode']} ({video_path.name})")
        log.info(f"    Titulo: {title[:50]}")
        if publish_at:
            log.info(f"    Programado: {publish_at}")
        else:
            log.info(f"    Publicacion: INMEDIATA")
        
        try:
            response = upload_to_youtube(
                youtube=youtube,
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                publish_at=publish_at
            )
            
            video_url = f"https://youtube.com/shorts/{response['id']}"
            log.info(f"    OK: {video_url}")
            
            # Update DB
            db.execute("""
                UPDATE uploads SET status = 'subido', url = ?, uploaded_at = ?
                WHERE id = ?
            """, (video_url, datetime.now().isoformat(), row['upload_id']))
            
            db.execute("UPDATE memes SET status = 'subido' WHERE shortcode = ?", (row['shortcode'],))
            db.commit()
            
            uploaded += 1
            time.sleep(3)  # Delay between uploads
            
        except Exception as e:
            log.error(f"    Error upload: {str(e)[:200]}")
            db.execute("""
                UPDATE uploads SET status = 'error', error_msg = ?
                WHERE id = ?
            """, (str(e)[:500], row['upload_id']))
            db.commit()
            errors += 1
    
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   RESUMEN UPLOAD")
    log.info(f"{'='*55}")
    log.info(f"   Subidos: {uploaded}")
    log.info(f"   Errores: {errors}")
    log.info(f"{'='*55}")


# ============================================================
# MAIN
# ============================================================

def start_local_server():
    os.chdir(str(SCRIPT_DIR))
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *args: None
    server = http.server.HTTPServer(('127.0.0.1', SERVER_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="Upload Social - YouTube Shorts")
    parser.add_argument('--generate-meta', action='store_true', help="Solo genera metadata")
    parser.add_argument('--upload', action='store_true', help="Ejecuta uploads pendientes")
    parser.add_argument('--apply', action='store_true', help="Aplica schedule del JSON")
    parser.add_argument('--auth', action='store_true', help="Solo autenticar con YouTube")
    parser.add_argument('--auto', action='store_true', help="Full auto: meta + schedule + upload")
    parser.add_argument('--status', action='store_true', help="Ver estado de uploads")
    parser.add_argument('--results-path', type=str, default=None)
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('upload_social')
    log = get_logger()
    ensure_upload_columns()
    
    if args.auth:
        log.info("Autenticando con YouTube...")
        try:
            youtube = get_youtube_service()
            log.info("Autenticacion exitosa! Token guardado.")
        except Exception as e:
            log.error(f"Error: {e}")
        return
    
    if args.apply:
        apply_schedule(args.results_path)
        return
    
    if args.upload:
        execute_uploads()
        return
    
    if args.auto:
        # Full auto: generate meta + auto-schedule + upload
        generate_all_metadata()
        videos = get_videos_for_upload()
        if not videos:
            log.info("No hay videos para programar.")
            return
        log.info("Auto-scheduling...")
        try:
            youtube = get_youtube_service()
            slots = find_next_available_slots(youtube, len(videos))
        except Exception as e:
            log.error(f"Error conectando YouTube: {e}")
            return
        db = get_db()
        for i, v in enumerate(videos):
            if i < len(slots):
                from zoneinfo import ZoneInfo
                local_tz = ZoneInfo(TIMEZONE)
                utc_tz = ZoneInfo('UTC')
                slot_utc = slots[i].astimezone(utc_tz)
                publish_at = slot_utc.strftime('%Y-%m-%dT%H:%M:%S.000Z')
                db.execute("""
                    UPDATE uploads SET scheduled_at = ?
                    WHERE video_id = ? AND status = 'pendiente'
                """, (slots[i].strftime('%Y-%m-%dT%H:%M'), v['video_id']))
                log.info(f"  {v['shortcode']} -> {slots[i].strftime('%Y-%m-%d %H:%M')} MX")
        db.commit()
        log.info("Subiendo con auto-schedule...")
        execute_uploads()
        return
    
    if args.generate_meta:
        generate_all_metadata()
        return
    
    if args.status:
        db = get_db()
        rows = db.execute("""
            SELECT u.status, COUNT(*) as cnt 
            FROM uploads u GROUP BY u.status
        """).fetchall()
        log.info("Upload status:")
        for r in rows:
            log.info(f"  {r['status']}: {r['cnt']}")
        return
    
    # Default: generate metadata + auto-schedule + open interface
    generate_all_metadata()
    
    videos = get_videos_for_upload()
    if not videos:
        log.info("No hay videos para programar.")
        return
    
    # Auto-assign schedule slots
    log.info("Consultando YouTube para slots disponibles...")
    try:
        youtube = get_youtube_service()
        slots = find_next_available_slots(youtube, len(videos))
        auto_dates = [s.strftime('%Y-%m-%dT%H:%M') for s in slots]
        generate_scheduler_html._auto_dates = auto_dates
        log.info(f"  {len(auto_dates)} slots encontrados")
    except Exception as e:
        log.warning(f"  No se pudo auto-programar: {e}")
        log.info("  Usa la interfaz para asignar horarios manualmente")
        generate_scheduler_html._auto_dates = []
    
    html = generate_scheduler_html(videos)
    META_HTML.write_text(html, encoding='utf-8')
    
    server = start_local_server()
    time.sleep(0.5)
    url = f"http://127.0.0.1:{SERVER_PORT}/upload_scheduler.html"
    webbrowser.open(url)
    
    log.info(f"")
    log.info(f"   Upload Scheduler abierto")
    log.info(f"   Videos: {len(videos)}")
    log.info(f"   Puerto: {SERVER_PORT}")
    log.info(f"")
    log.info(f"   Flujo:")
    log.info(f"     1. Edita titulos/descripciones")
    log.info(f"     2. Programa fecha/hora de publicacion")
    log.info(f"     3. GUARDAR SCHEDULE")
    log.info(f"     4. python 9_upload_social.py --apply")
    log.info(f"     5. python 9_upload_social.py --upload")
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
