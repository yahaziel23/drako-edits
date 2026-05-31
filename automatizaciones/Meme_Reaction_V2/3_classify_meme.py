#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - 3 Classify Meme

Clasifica memes con GPT-4o Vision. Extrae toda la info necesaria para
el pipeline en UNA sola llamada (la imagen ya se pago, maximo provecho).

Extrae:
- valido: es meme o es basura
- es_video_real: si el frame no funciona como meme estatico
- categorias: 2-6 tags del taxonomy expandido
- confianza: 0.0 a 1.0
- descripcion: descripcion detallada del meme
- ideas_video: 5 ideas creativas de como usar el meme
- background_color: color de fondo dominante
- dia_especial: si aplica (viernes, halloween, etc)

Uso:
    python 3_classify_meme.py                   # Clasifica pendientes
    python 3_classify_meme.py --max 5           # Solo 5 memes
    python 3_classify_meme.py --reclasificar    # Re-clasifica todos
    python 3_classify_meme.py --reclasificar --version 2  # Solo los de prompt v2
    python 3_classify_meme.py --dry-run         # Muestra que haria sin gastar tokens

Dependencias: openai, Pillow, python-dotenv
"""

import sys
import os
import json
import base64
import argparse
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime

# Cargar .env ANTES de todo
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / '.env')

sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db, update_meme_status, log_api_request
from utils.config import load_config, get_config, get_section
from utils.logger import setup_logger, get_logger, track_tokens, track_item
from utils.rate_limiter import RateLimiter
from utils.retry import retry_openai

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: pip install openai")
    sys.exit(1)


# =============================================================================
# PROMPT
# =============================================================================

PROMPT_VERSION = 2

SYSTEM_PROMPT = """Eres un experto analizador de memes para un canal de videos de reaccion.
Tu trabajo es clasificar memes con precision para un pipeline automatizado.

Responde SIEMPRE en JSON valido. Sin markdown, sin texto adicional."""

USER_PROMPT_TEMPLATE = """Analiza este meme y devuelve un JSON con la siguiente estructura exacta:

{{
  "valido": true/false,
  "es_video_real": true/false,
  "confianza": 0.0-1.0,
  "categorias": ["tag1", "tag2", ...],
  "descripcion": "descripcion detallada del meme",
  "ideas_video": [
    "idea 1",
    "idea 2",
    "idea 3",
    "idea 4",
    "idea 5"
  ],
  "background_color": "#RRGGBB",
  "dia_especial": null o "viernes"/"halloween"/"navidad"/etc
}}

REGLAS:
- "valido": false si es publicidad, selfie, paisaje, foto random sin humor, o contenido que no sirve como meme
- "es_video_real": true si la imagen es un frame de video que NO funciona como meme estatico (ej: frame borroso, sin contexto sin audio)
- "categorias": escoge 2-6 tags de esta lista (o inventa uno si nada aplica):

  FORMATO: formato_texto_arriba_imagen_abajo, formato_solo_imagen, formato_texto_overlay, formato_dos_paneles, formato_multi_panel, formato_screenshot_chat, formato_screenshot_tweet, formato_screenshot_comentario, formato_reaccion_con_caption, formato_edit_shitpost, formato_lista_ranking

  HUMOR: humor_absurdo, humor_dark, humor_sexual, humor_cringe, humor_wholesome, humor_ironia, humor_sarcasmo, humor_anti_meme, humor_meta, humor_intelectual

  NARRATIVA: narrativa_plot_twist, narrativa_expectativa_vs_realidad, narrativa_pov, narrativa_nadie_absolutamente_nadie, narrativa_yo_vs_mi_cerebro, narrativa_before_after, narrativa_escalamiento, narrativa_confesion, narrativa_comparacion_falsa, narrativa_literalidad

  EMOCION: reaccion_sorpresa, reaccion_indignacion, reaccion_tristeza_comica, reaccion_panico, reaccion_orgullo_culposo, reaccion_nostalgia, reaccion_relatable, reaccion_flexeo

  TEMATICA: tema_relaciones, tema_familia, tema_trabajo, tema_escuela, tema_gaming, tema_internet_cultura, tema_dinero, tema_comida, tema_animales, tema_mexico_latam, tema_musica, tema_deporte, tema_politica_light, tema_existencial

  TONO: tono_suave, tono_medio, tono_fuerte, tono_NSFW_light

- OBLIGATORIO al menos 1 tag de FORMATO + 1 tag de HUMOR

- "ideas_video": 5 ideas DIFERENTES para usar este meme en un video corto.
  ESTRUCTURA FIJA (la unica por ahora): el video es MEME (imagen) + CAPTION (texto corto opcional sobre el meme) + CLIP DE REACCION (video corto de alguien reaccionando).
  Para cada idea escribe SOLO:
    1. Que tipo de clip de reaccion queda (descripcion del clip ideal, ej: "persona riendose a carcajadas", "alguien escupiendo agua de risa")
    2. Un caption CORTO para poner sobre el meme (maximo 6-8 palabras, estilo TikTok/Reels). Si no necesita caption escribe "sin caption".
  
  IMPORTANTE sobre las ideas:
  - Las 5 ideas DEBEN ser coherentes con el TONO del meme. Si el meme es gracioso, las 5 reacciones deben ser humoristicas/de risa. NO mezcles reacciones de nostalgia, confusion o analisis si el meme es puramente comico.
  - Formato de cada idea: "Clip: [descripcion del clip]. Caption: [texto corto o 'sin caption']"
  - NO describas la estructura del video (ya es fija). Solo el clip y el caption.
  - Se CREATIVO y VARIADO en los clips. No repitas el mismo tipo de reaccion.

- "background_color": el color hexadecimal dominante del fondo del meme
- "dia_especial": solo si el meme es especifico para un dia/fecha (null si es generico)
- "descripcion": se DETALLADO. Alguien que no ve la imagen debe entender el meme completo con tu descripcion. Incluye: que se ve en la imagen, que dice el texto, cual es el chiste/referencia.
"""


# =============================================================================
# CLASIFICACION
# =============================================================================

def image_to_base64(image_path):
    """Convierte imagen a base64 para la API de OpenAI."""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


@retry_openai
def classify_single_meme(client, image_path, model='gpt-4o'):
    """
    Clasifica un meme con GPT-4o Vision.
    Retorna el dict parseado o None si falla.
    """
    b64 = image_to_base64(image_path)
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": USER_PROMPT_TEMPLATE},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": "low"
                        }
                    }
                ]
            }
        ],
        max_tokens=1500,
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    
    content = response.choices[0].message.content.strip()
    
    # Limpiar posibles markdown fences (robusto)
    import re
    fence_match = re.search(r'```(?:json)?\s*\n?(\{.*\})\s*\n?```', content, re.DOTALL)
    if fence_match:
        content = fence_match.group(1).strip()
    else:
        # Fallback: buscar el primer { y ultimo }
        first_brace = content.find('{')
        last_brace = content.rfind('}')
        if first_brace != -1 and last_brace != -1:
            content = content[first_brace:last_brace + 1]
    content = content.strip()
    
    result = json.loads(content)
    
    usage = {
        'prompt_tokens': response.usage.prompt_tokens,
        'completion_tokens': response.usage.completion_tokens,
        'total_tokens': response.usage.total_tokens,
    }
    
    return result, usage


# =============================================================================
# DATABASE: guardar clasificacion
# =============================================================================

REQUIRED_COLUMNS = [
    'shortcode', 'valido', 'es_video_real', 'confianza', 'categorias',
    'descripcion', 'ideas_video', 'background_color', 'dia_especial',
    'prompt_version', 'tokens_used', 'classified_at', 'raw_response'
]


def ensure_clasificaciones_table():
    """
    Asegura que la tabla clasificaciones tenga el schema correcto.
    Si existe con schema viejo (sin prompt_version, etc), la dropea y recrea.
    """
    db = get_db()
    
    # Verificar si la tabla existe
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='clasificaciones'"
    ).fetchone()
    
    if exists:
        # Verificar que tenga todas las columnas necesarias
        columns = [row[1] for row in db.execute("PRAGMA table_info(clasificaciones)").fetchall()]
        missing = [c for c in REQUIRED_COLUMNS if c not in columns]
        
        if missing:
            # Schema viejo - contar filas para decidir
            count = db.execute("SELECT COUNT(*) FROM clasificaciones").fetchone()[0]
            if count == 0:
                # Tabla vacia con schema viejo -> drop y recrear
                db.execute("DROP TABLE clasificaciones")
                db.commit()
            else:
                # Tiene datos - agregar columnas faltantes
                for col in missing:
                    db.execute(f"ALTER TABLE clasificaciones ADD COLUMN {col} TEXT")
                db.commit()
                return
    
    # Crear con schema completo
    db.execute("""
        CREATE TABLE IF NOT EXISTS clasificaciones (
            shortcode TEXT PRIMARY KEY,
            valido INTEGER,
            es_video_real INTEGER,
            confianza REAL,
            categorias TEXT,
            descripcion TEXT,
            ideas_video TEXT,
            background_color TEXT,
            dia_especial TEXT,
            prompt_version INTEGER,
            tokens_used INTEGER,
            classified_at TEXT,
            raw_response TEXT
        )
    """)
    db.commit()


def save_classification(shortcode, result, usage, prompt_version):
    """Guarda la clasificacion en SQLite."""
    db = get_db()
    
    db.execute("""
        INSERT OR REPLACE INTO clasificaciones
        (shortcode, valido, es_video_real, confianza, categorias, descripcion,
         ideas_video, background_color, dia_especial, prompt_version, tokens_used,
         classified_at, raw_response)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        shortcode,
        1 if result.get('valido', False) else 0,
        1 if result.get('es_video_real', False) else 0,
        result.get('confianza', 0.0),
        json.dumps(result.get('categorias', []), ensure_ascii=False),
        result.get('descripcion', ''),
        json.dumps(result.get('ideas_video', []), ensure_ascii=False),
        result.get('background_color', ''),
        result.get('dia_especial'),
        prompt_version,
        usage.get('total_tokens', 0),
        datetime.now().isoformat(),
        json.dumps(result, ensure_ascii=False),
    ))
    db.commit()


# =============================================================================
# OBTENER MEMES A CLASIFICAR
# =============================================================================

def get_memes_to_classify(max_count=None, reclasificar=False, version_filter=None):
    """Obtiene memes pendientes de clasificacion."""
    db = get_db()
    
    if reclasificar:
        if version_filter is not None:
            rows = db.execute("""
                SELECT m.shortcode, m.image_path, m.image_hash
                FROM memes m
                JOIN clasificaciones c ON m.shortcode = c.shortcode
                WHERE c.prompt_version = ?
                ORDER BY m.likes DESC
            """, (version_filter,)).fetchall()
        else:
            rows = db.execute("""
                SELECT m.shortcode, m.image_path, m.image_hash
                FROM memes m
                JOIN clasificaciones c ON m.shortcode = c.shortcode
                ORDER BY m.likes DESC
            """).fetchall()
    else:
        rows = db.execute("""
            SELECT shortcode, image_path, image_hash
            FROM memes
            WHERE status = 'listo_clasificar'
            ORDER BY likes DESC
        """).fetchall()
    
    memes = []
    for row in rows:
        shortcode = row['shortcode']
        img_path = Path(row['image_path']) if row['image_path'] else SCRIPT_DIR / "memes_descargados" / f"{shortcode}.jpg"
        
        if not img_path.exists():
            continue
        
        memes.append({
            'shortcode': shortcode,
            'image_path': img_path,
            'image_hash': row['image_hash'],
        })
    
    if max_count:
        memes = memes[:max_count]
    
    return memes


def check_hash_cache(image_hash):
    """Verifica si ya existe una clasificacion con este hash (imagen duplicada)."""
    if not image_hash:
        return None
    db = get_db()
    try:
        row = db.execute("""
            SELECT c.* FROM clasificaciones c
            JOIN memes m ON c.shortcode = m.shortcode
            WHERE m.image_hash = ? AND c.prompt_version = ?
            LIMIT 1
        """, (image_hash, PROMPT_VERSION)).fetchone()
        return dict(row) if row else None
    except Exception:
        # Si la tabla tiene schema viejo, skip cache
        return None


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="3 Classify Meme - GPT-4o Vision")
    parser.add_argument('--max', type=int, default=None,
                        help="Maximo de memes a clasificar")
    parser.add_argument('--reclasificar', action='store_true',
                        help="Re-clasifica memes ya clasificados")
    parser.add_argument('--version', type=int, default=None,
                        help="Solo re-clasificar los de esta version de prompt")
    parser.add_argument('--dry-run', action='store_true',
                        help="Muestra que haria sin gastar tokens")
    args = parser.parse_args()

    # Setup
    setup_logger('3_classify')
    log = get_logger()
    load_config()
    init_db()
    ensure_clasificaciones_table()

    # Rate limiter
    limiter = RateLimiter('openai')

    # Obtener memes
    memes = get_memes_to_classify(
        max_count=args.max,
        reclasificar=args.reclasificar,
        version_filter=args.version
    )

    if not memes:
        log.info("No hay memes pendientes de clasificacion.")
        return

    log.info(f"Clasificando {len(memes)} memes con GPT-4o Vision...")
    log.info(f"  Prompt version: {PROMPT_VERSION}")
    log.info(f"  Modelo: gpt-4o (detail:low)")
    if args.dry_run:
        log.info("  [DRY RUN - no se gastan tokens]")
    print("")

    # Inicializar cliente OpenAI
    client = None
    if not args.dry_run:
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            log.error("OPENAI_API_KEY no encontrada en environment.")
            log.error("  Verifica tu .env en la carpeta del proyecto.")
            return
        client = OpenAI(api_key=api_key)

    # Procesar cada meme
    stats = {
        'total': 0, 'validos': 0, 'invalidos': 0,
        'cached': 0, 'errors': 0, 'tokens': 0
    }

    for i, meme in enumerate(memes, 1):
        shortcode = meme['shortcode']
        log.info(f"  [{i}/{len(memes)}] {shortcode}")

        # Check rate limit
        if not args.dry_run and not limiter.can_request():
            log.warning("Rate limit alcanzado. Deteniendo.")
            break

        # Check cache por hash
        if not args.reclasificar and meme['image_hash']:
            cached = check_hash_cache(meme['image_hash'])
            if cached:
                log.info(f"    -> CACHE HIT (mismo hash que {cached['shortcode']})")
                result = json.loads(cached['raw_response'])
                save_classification(shortcode, result, {'total_tokens': 0}, PROMPT_VERSION)
                if result.get('valido') and not result.get('es_video_real'):
                    update_meme_status(shortcode, 'pendiente_match')
                else:
                    update_meme_status(shortcode, 'descartado_ia')
                stats['cached'] += 1
                stats['total'] += 1
                continue

        # Dry run
        if args.dry_run:
            log.info(f"    -> [DRY] Se clasificaria: {meme['image_path'].name}")
            stats['total'] += 1
            continue

        # Clasificar con OpenAI
        try:
            result, usage = classify_single_meme(client, meme['image_path'])
            
            # Log tokens
            tokens = usage.get('total_tokens', 0)
            stats['tokens'] += tokens
            track_tokens(tokens)
            limiter.log_request(tokens=tokens)
            log_api_request('openai', tokens)

            # Guardar en DB
            save_classification(shortcode, result, usage, PROMPT_VERSION)

            # Actualizar status del meme
            valido = result.get('valido', False)
            es_video_real = result.get('es_video_real', False)

            if valido and not es_video_real:
                update_meme_status(shortcode, 'pendiente_match')
                stats['validos'] += 1
                cats = result.get('categorias', [])[:3]
                log.info(f"    -> VALIDO | {', '.join(cats)} | {tokens} tok")
            else:
                update_meme_status(shortcode, 'descartado_ia')
                stats['invalidos'] += 1
                reason = "video_real" if es_video_real else "no_valido"
                log.info(f"    -> DESCARTADO ({reason}) | {tokens} tok")

            stats['total'] += 1

        except json.JSONDecodeError as e:
            log.error(f"    -> ERROR JSON: {e}")
            stats['errors'] += 1
            stats['total'] += 1
        except Exception as e:
            log.error(f"    -> ERROR: {e}")
            stats['errors'] += 1
            stats['total'] += 1

    # Resumen
    print("")
    print("=" * 60)
    print("   CLASIFICACION COMPLETADA")
    print("=" * 60)
    print(f"   Total procesados:     {stats['total']}")
    print(f"   Validos (-> match):   {stats['validos']}")
    print(f"   Descartados (IA):     {stats['invalidos']}")
    print(f"   Cache hits:           {stats['cached']}")
    print(f"   Errores:              {stats['errors']}")
    print(f"   Tokens gastados:      {stats['tokens']:,}")
    print(f"   Prompt version:       {PROMPT_VERSION}")
    if args.dry_run:
        print("   [DRY RUN - nada fue procesado]")
    print("=" * 60)
    print("")
    print("   Siguiente paso: python view_clasificados.py")
    print("")


if __name__ == "__main__":
    main()
