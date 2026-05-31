#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Match Meme <-> Clip con IA

Para cada meme en status 'pendiente_match':
  1. Lee su clasificacion (categorias, ideas_video, descripcion)
  2. Lee todos los clips categorizados por IA
  3. Usa GPT-4o-mini para scoring de compatibilidad (0-100)
  4. Genera 1-2 captions por cada combinacion meme+clip
  5. Guarda top 3 matches + sugerencias de YouTube si ninguno >90%

Requisitos:
    pip install openai python-dotenv
    OPENAI_API_KEY en .env

Uso:
    python 4_match_clip.py                    # Matchear todos los pendientes
    python 4_match_clip.py --shortcode ABC    # Solo un meme
    python 4_match_clip.py --dry-run          # Preview sin gastar
    python 4_match_clip.py --force            # Re-matchear incluso ya matcheados

Costo estimado: ~$0.005-0.01 por meme (GPT-4o-mini, texto only)
"""

import sys
import os
import json
import argparse
import time
import base64
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR / '.env')

from utils.db import init_db, get_db
from utils.config import load_config
from utils.logger import setup_logger, get_logger

MEMES_DIR = SCRIPT_DIR / "memes"
CLIPS_DIR = SCRIPT_DIR / "clips"

# ============================================================
# PROMPT PARA MATCHING
# ============================================================
MATCH_PROMPT = """Eres un experto en edicion de memes para TikTok/Reels.

Te doy un MEME y una lista de CLIPS de reaccion disponibles.
Tu trabajo: decidir que clip queda MEJOR como reaccion debajo del meme.

El video final es vertical (1080x1920):
  - Meme arriba (~65% del frame)
  - Caption en medio (texto corto estilo TikTok, max 6-8 palabras)
  - Clip de reaccion abajo (~30% del frame)

=== MEME ===
Descripcion: {meme_descripcion}
Categorias: {meme_categorias}
Tono: {meme_tono}

=== CLIPS DISPONIBLES ===
{clips_info}

=== INSTRUCCIONES ===
Responde con un JSON valido (sin markdown, sin ```):
{{
  "matches": [
    {{
      "clip_id": "id_del_clip",
      "compatibilidad": 85,
      "razon": "Explicacion breve de por que este clip queda bien con este meme",
      "captions": [
        "Caption opcion 1 (max 6-8 palabras, estilo TikTok)",
        "Caption opcion 2"
      ]
    }}
  ],
  "sin_caption_viable": false,
  "youtube_sugerencias": [
    "busqueda de youtube si ningun clip supera 70% de compatibilidad"
  ]
}}

REGLAS:
- Devuelve MAXIMO 5 matches, ordenados de mayor a menor compatibilidad
- compatibilidad: 0-100 (100 = match perfecto)
- Si NINGUN clip supera 70%, agrega 3-5 sugerencias de busqueda YouTube
- Captions: max 6-8 palabras, humor mexicano/latino, estilo TikTok
- Si el meme funciona mejor SIN caption, pon sin_caption_viable=true
- Piensa: ¿este clip como REACCION al meme tiene sentido? ¿es gracioso?
- El clip debe REACCIONAR al meme, no repetir lo mismo
"""


def get_pending_memes(force=False, shortcode=None):
    """Obtiene memes listos para matching."""
    db = get_db()
    
    if shortcode:
        rows = db.execute("""
            SELECT m.shortcode, m.image_path, c.descripcion, c.categorias, 
                   c.ideas_video, c.confianza
            FROM memes m
            JOIN clasificaciones c ON m.shortcode = c.shortcode
            WHERE m.shortcode = ?
        """, (shortcode,)).fetchall()
    elif force:
        rows = db.execute("""
            SELECT m.shortcode, m.image_path, c.descripcion, c.categorias,
                   c.ideas_video, c.confianza
            FROM memes m
            JOIN clasificaciones c ON m.shortcode = c.shortcode
            WHERE m.status IN ('pendiente_match', 'match_review', 'buscar_clip')
        """).fetchall()
    else:
        rows = db.execute("""
            SELECT m.shortcode, m.image_path, c.descripcion, c.categorias,
                   c.ideas_video, c.confianza
            FROM memes m
            JOIN clasificaciones c ON m.shortcode = c.shortcode
            WHERE m.status = 'pendiente_match'
        """).fetchall()
    
    return rows


def get_categorized_clips():
    """Obtiene todos los clips con categorizacion IA."""
    db = get_db()
    rows = db.execute("""
        SELECT id, descripcion, descripcion_corta, categorias, mood, intensidad,
               audio_analisis, compatibilidad_meme, duracion_s, filename
        FROM clips
        WHERE categorizado_ia_at IS NOT NULL
        AND COALESCE(approved, 0) = 1
    """).fetchall()
    
    clips = []
    for row in rows:
        cats = []
        compat = []
        try:
            cats = json.loads(row['categorias']) if row['categorias'] else []
        except Exception:
            pass
        try:
            compat = json.loads(row['compatibilidad_meme']) if row['compatibilidad_meme'] else []
        except Exception:
            pass
        
        clips.append({
            'id': row['id'],
            'descripcion': row['descripcion'] or '',
            'descripcion_corta': row['descripcion_corta'] or '',
            'categorias': cats,
            'mood': row['mood'] or '',
            'intensidad': row['intensidad'] or 5,
            'compatibilidad_meme': compat,
            'duracion_s': row['duracion_s'] or 0,
            'filename': row['filename'],
        })
    
    return clips


def build_clips_info(clips):
    """Formatea info de clips para el prompt."""
    parts = []
    for i, c in enumerate(clips):
        cats_str = ', '.join(c['categorias'][:5])
        compat_str = ' | '.join(c['compatibilidad_meme'][:3])
        parts.append(
            f"CLIP {i+1} (id: {c['id']}):\n"
            f"  Descripcion: {c['descripcion_corta']}\n"
            f"  Tags: {cats_str}\n"
            f"  Mood: {c['mood']} | Intensidad: {c['intensidad']}/10\n"
            f"  Compatible con: {compat_str}\n"
            f"  Duracion: {c['duracion_s']:.1f}s"
        )
    return '\n\n'.join(parts)


def match_meme_with_clips(meme, clips, api_key):
    """Usa GPT-4o-mini para encontrar el mejor match meme<->clip."""
    from openai import OpenAI
    
    log = get_logger()
    client = OpenAI(api_key=api_key)
    
    # Parse meme data
    meme_cats = []
    try:
        meme_cats = json.loads(meme['categorias']) if meme['categorias'] else []
    except Exception:
        pass
    
    meme_tono = 'medio'
    for cat in meme_cats:
        if cat.startswith('tono_'):
            meme_tono = cat.replace('tono_', '')
            break
    
    # Build prompt
    clips_info = build_clips_info(clips)
    
    prompt = MATCH_PROMPT.format(
        meme_descripcion=meme['descripcion'] or 'Sin descripcion',
        meme_categorias=', '.join(meme_cats),
        meme_tono=meme_tono,
        clips_info=clips_info
    )
    
    # Also send the meme image for visual context
    messages = [{"role": "user", "content": []}]
    
    # Try to include meme image
    meme_image_path = MEMES_DIR / (meme['shortcode'] + '.jpg') if meme['image_path'] is None else MEMES_DIR / meme['image_path']
    if not meme_image_path.exists():
        # Try common patterns
        for ext in ['.jpg', '.png', '.webp']:
            candidate = MEMES_DIR / (meme['shortcode'] + ext)
            if candidate.exists():
                meme_image_path = candidate
                break
    
    if meme_image_path.exists():
        with open(meme_image_path, 'rb') as f:
            img_b64 = base64.b64encode(f.read()).decode('utf-8')
        
        # Determine mime type
        ext = meme_image_path.suffix.lower()
        mime = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png' if ext == '.png' else 'image/webp'
        
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{img_b64}", "detail": "low"}
        })
    
    messages[0]["content"].append({"type": "text", "text": prompt})
    
    # Call GPT-4o-mini
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=1500,
        temperature=0.4,
        response_format={"type": "json_object"}
    )
    
    raw_text = response.choices[0].message.content.strip()
    result = json.loads(raw_text)
    
    # Log usage
    usage = response.usage
    log.info(f"    Tokens: {usage.total_tokens} | Costo: ~${usage.total_tokens * 0.00000015:.5f}")
    
    return result


def save_matches(shortcode, match_result, clips_lookup):
    """Guarda los matches en SQLite."""
    db = get_db()
    log = get_logger()
    
    # Delete previous matches for this meme
    db.execute("DELETE FROM matches WHERE shortcode = ?", (shortcode,))
    
    matches = match_result.get('matches', [])
    youtube_sugs = match_result.get('youtube_sugerencias', [])
    sin_caption = match_result.get('sin_caption_viable', False)
    
    # Get valid clip IDs from DB
    valid_clips = set(row[0] for row in db.execute("SELECT id FROM clips").fetchall())
    
    best_score = 0
    inserted = 0
    
    for i, m in enumerate(matches):
        clip_id = m.get('clip_id', '').strip()
        score = m.get('compatibilidad', 0)
        razon = m.get('razon', '')
        captions = json.dumps(m.get('captions', []), ensure_ascii=False)
        
        # Validate clip_id exists (GPT sometimes modifies IDs slightly)
        if clip_id not in valid_clips:
            # Try fuzzy match (find closest)
            matched_id = None
            for vid in valid_clips:
                if clip_id in vid or vid in clip_id:
                    matched_id = vid
                    break
            if matched_id:
                log.warning(f"    Clip ID corregido: {clip_id[:30]} -> {matched_id[:30]}")
                clip_id = matched_id
            else:
                log.warning(f"    Clip ID invalido (skip): {clip_id[:40]}")
                continue
        
        if score > best_score:
            best_score = score
        
        db.execute("""
            INSERT INTO matches (shortcode, clip_id, accuracy, caption, match_type, 
                                 caption_size, match_rank, razon, captions_json, youtube_sugerencias)
            VALUES (?, ?, ?, ?, 'auto', 'M', ?, ?, ?, ?)
        """, (
            shortcode, clip_id, score,
            m.get('captions', [''])[0] if m.get('captions') else '',
            inserted + 1,
            razon,
            captions,
            json.dumps(youtube_sugs, ensure_ascii=False) if inserted == 0 else None
        ))
        inserted += 1
    
    # Update meme status based on best score
    if best_score >= 90:
        new_status = 'por_generar'  # Auto-accept
    elif best_score >= 40:
        new_status = 'match_review'  # Needs human review
    else:
        new_status = 'buscar_clip'  # No good match
    
    db.execute("UPDATE memes SET status = ? WHERE shortcode = ?", (new_status, shortcode))
    db.commit()
    
    return best_score, new_status


def ensure_match_columns():
    """Asegura que la tabla matches tenga las columnas necesarias."""
    db = get_db()
    new_columns = [
        ("match_rank", "INTEGER DEFAULT 1"),
        ("razon", "TEXT"),
        ("captions_json", "TEXT"),
        ("youtube_sugerencias", "TEXT"),
    ]
    for col_name, col_type in new_columns:
        try:
            db.execute(f"ALTER TABLE matches ADD COLUMN {col_name} {col_type}")
            db.commit()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Match memes con clips usando IA")
    parser.add_argument('--force', action='store_true', help="Re-matchear todos")
    parser.add_argument('--shortcode', type=str, default=None, help="Solo un meme")
    parser.add_argument('--dry-run', action='store_true', help="Preview sin gastar")
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('match_clip')
    log = get_logger()
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        log.error("OPENAI_API_KEY no encontrada en .env")
        sys.exit(1)
    
    ensure_match_columns()
    
    # Get data
    memes = get_pending_memes(force=args.force, shortcode=args.shortcode)
    clips = get_categorized_clips()
    
    if not memes:
        log.info("No hay memes pendientes de match.")
        log.info("Usa --force para re-matchear, o clasifica mas memes primero.")
        return
    
    if not clips:
        log.error("No hay clips categorizados. Corre primero: python 3b_categorizar_clips.py")
        return
    
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   MATCH MEME <-> CLIP")
    log.info(f"{'='*55}")
    log.info(f"   Memes a matchear: {len(memes)}")
    log.info(f"   Clips disponibles: {len(clips)}")
    log.info(f"   Modelo: GPT-4o-mini (con imagen del meme)")
    log.info(f"   Costo estimado: ~${len(memes) * 0.008:.3f}")
    log.info(f"{'='*55}")
    log.info(f"")
    
    if args.dry_run:
        log.info("[DRY RUN] Memes que se matchearian:")
        for m in memes:
            cats = json.loads(m['categorias']) if m['categorias'] else []
            log.info(f"  {m['shortcode']} | {', '.join(cats[:3])} | conf={m['confianza']}")
        log.info(f"\nClips disponibles:")
        for c in clips:
            log.info(f"  {c['id'][:25]} | {c['descripcion_corta'][:40]} | {c['mood']}")
        return
    
    # Build clips lookup
    clips_lookup = {c['id']: c for c in clips}
    
    # Process
    auto_accepted = 0
    needs_review = 0
    no_match = 0
    errors = 0
    
    for i, meme in enumerate(memes):
        log.info(f"  [{i+1}/{len(memes)}] Meme: {meme['shortcode']}")
        
        cats = []
        try:
            cats = json.loads(meme['categorias']) if meme['categorias'] else []
        except Exception:
            pass
        log.info(f"    Tags: {', '.join(cats[:4])}")
        
        try:
            result = match_meme_with_clips(meme, clips, api_key)
            best_score, new_status = save_matches(meme['shortcode'], result, clips_lookup)
            
            matches_found = result.get('matches', [])
            top_match = matches_found[0] if matches_found else {}
            
            log.info(f"    Best match: {top_match.get('clip_id', '?')[:25]} ({best_score}%)")
            log.info(f"    Caption: {top_match.get('captions', [''])[0][:50]}")
            log.info(f"    Status -> {new_status}")
            
            if new_status == 'por_generar':
                auto_accepted += 1
            elif new_status == 'match_review':
                needs_review += 1
            else:
                no_match += 1
                yt = result.get('youtube_sugerencias', [])
                if yt:
                    log.info(f"    YouTube sugerencias: {yt[0]}")
            
        except Exception as e:
            log.error(f"    ERROR: {str(e)[:150]}")
            errors += 1
        
        # Delay between memes
        if i < len(memes) - 1:
            time.sleep(2)
    
    # Summary
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   RESUMEN MATCHING")
    log.info(f"{'='*55}")
    log.info(f"   Auto-aceptados (>=90%): {auto_accepted}")
    log.info(f"   Para revision (40-89%): {needs_review}")
    log.info(f"   Sin match (<40%):       {no_match}")
    log.info(f"   Errores:                {errors}")
    log.info(f"{'='*55}")
    log.info(f"")
    log.info(f"   Siguiente paso:")
    if needs_review > 0 or auto_accepted > 0:
        log.info(f"     python catalogo_matches.py")
        log.info(f"     (interfaz para revisar matches y tomar decisiones)")
    if no_match > 0:
        log.info(f"     Descarga mas clips con las sugerencias de YouTube")
        log.info(f"     python descargar_clips.py --batch ...")


if __name__ == "__main__":
    main()
