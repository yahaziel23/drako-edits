#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Categorizar Clips con IA

Soporta 2 motores:
  - OpenAI GPT-4o (default): Extrae 5 frames y los analiza como imagenes. ~$0.035/clip
  - Gemini 2.0 Flash: Analiza video+audio completo. ~$0.001/clip (requiere billing Google)

Genera por clip:
  - Descripcion detallada (que pasa visualmente)
  - Categorias (misma taxonomia de 55 tags del proyecto)
  - Mood/energia del clip
  - Analisis de audio (inferido del contexto visual con OpenAI, directo con Gemini)
  - Recomendaciones (recortar, cambiar audio, tipo de meme ideal)
  - Intensidad (1-10)

Requisitos:
    pip install openai python-dotenv     # Para modo OpenAI (default)
    pip install google-genai             # Para modo Gemini (opcional)
    OPENAI_API_KEY en .env               # Para modo OpenAI
    GOOGLE_API_KEY en .env               # Para modo Gemini

Uso:
    python 3b_categorizar_clips.py                    # GPT-4o (default)
    python 3b_categorizar_clips.py --model gemini     # Gemini (requiere billing)
    python 3b_categorizar_clips.py --force            # Re-categoriza todos
    python 3b_categorizar_clips.py --id CLIP_ID       # Solo un clip
    python 3b_categorizar_clips.py --dry-run          # Preview sin gastar

Costo estimado (22 clips):
    OpenAI: ~$0.70 total (~$0.035/clip, 5 frames x 85 tokens + texto)
    Gemini: ~$0.02 total (~$0.001/clip, video completo + audio)
"""

import sys
import os
import json
import argparse
import time
import subprocess
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR / '.env')

from utils.db import init_db, get_db
from utils.config import load_config
from utils.logger import setup_logger, get_logger
# from utils.retry import with_retry  # Custom retry logic inside analyze function

CLIPS_DIR = SCRIPT_DIR / "clips"

# ============================================================
# TAXONOMIA V2 (misma que 3_classify_meme.py)
# ============================================================
TAXONOMIA = {
    "FORMATO": [
        "formato_texto_arriba_imagen_abajo", "formato_solo_imagen", "formato_texto_overlay",
        "formato_dos_paneles", "formato_multi_panel", "formato_screenshot_chat",
        "formato_screenshot_tweet", "formato_screenshot_comentario",
        "formato_reaccion_con_caption", "formato_edit_shitpost", "formato_lista_ranking"
    ],
    "HUMOR": [
        "humor_absurdo", "humor_dark", "humor_sexual", "humor_cringe", "humor_wholesome",
        "humor_ironia", "humor_sarcasmo", "humor_anti_meme", "humor_meta", "humor_intelectual"
    ],
    "NARRATIVA": [
        "narrativa_plot_twist", "narrativa_expectativa_vs_realidad", "narrativa_pov",
        "narrativa_nadie_absolutamente_nadie", "narrativa_yo_vs_mi_cerebro",
        "narrativa_before_after", "narrativa_escalamiento", "narrativa_confesion",
        "narrativa_comparacion_falsa", "narrativa_literalidad"
    ],
    "EMOCION": [
        "reaccion_sorpresa", "reaccion_indignacion", "reaccion_tristeza_comica",
        "reaccion_panico", "reaccion_orgullo_culposo", "reaccion_nostalgia",
        "reaccion_relatable", "reaccion_flexeo"
    ],
    "TEMATICA": [
        "tema_relaciones", "tema_familia", "tema_trabajo", "tema_escuela",
        "tema_gaming", "tema_internet_cultura", "tema_dinero", "tema_comida",
        "tema_animales", "tema_mexico_latam", "tema_musica", "tema_deporte",
        "tema_politica_light", "tema_existencial"
    ],
    "TONO": [
        "tono_suave", "tono_medio", "tono_fuerte", "tono_NSFW_light"
    ]
}

ALL_TAGS = [tag for group in TAXONOMIA.values() for tag in group]

# ============================================================
# PROMPT PARA GEMINI
# ============================================================
CLIP_ANALYSIS_PROMPT = """Eres un experto en edicion de video de memes para TikTok/Reels.
Analiza este clip de reaccion (video + audio) y dame un JSON con tu analisis.

El clip se usa como REACCION debajo de un meme (ocupa ~30% inferior del video vertical 1080x1920).
Necesito saber exactamente que pasa en el clip para poder matchearlo con memes.

TAXONOMIA DE TAGS DISPONIBLES:
{tags_by_group}

Responde SOLO con un JSON valido (sin markdown, sin ```):
{{
  "descripcion": "Descripcion precisa de lo que pasa visualmente en el clip (2-3 oraciones)",
  "descripcion_corta": "Frase de 5-8 palabras que resume el clip (ej: 'persona se rie y se detiene')",
  "categorias": ["tag1", "tag2", "tag3"],
  "mood": "una palabra: epico | chill | caotico | dramatico | comico | tenso | nostalgico | energetico",
  "intensidad": 7,
  "audio_analisis": {{
    "tipo": "musica | dialogo | efecto_sonido | silencio | mixto",
    "descripcion": "Que se escucha (instrumento, genero, palabras, efectos...)",
    "tiene_beat_drop": true/false,
    "energia_audio": "baja | media | alta | explosiva",
    "sirve_como_audio_de_fondo": true/false
  }},
  "timing": {{
    "punch_moment_s": 4.5,
    "buildup_range": [0, 3],
    "mejor_rango_s": [2, 8],
    "inicio_muerto_s": 0
  }},
  "recomendaciones": {{
    "recortar": "No / Si: del segundo X al Y",
    "audio_original_sirve": true/false,
    "audio_sugerencia": "Descripcion del tipo de audio que le quedaria mejor (o 'el original esta bien')",
    "meme_ideal": "Tipo de meme con el que este clip pegaria perfecto (1-2 oraciones)"
  }},
  "compatibilidad_meme": [
    "Tipo de narrativa o emocion que matchea mejor (ej: plot_twist, reaccion_sorpresa)",
    "Segundo tipo compatible",
    "Tercer tipo compatible"
  ]
}}

REGLAS:
- categorias: usa 2-5 tags de la taxonomia. Si ninguno aplica, sugiere uno nuevo con formato grupo_nombre.
- intensidad: 1=super chill, 5=normal, 10=explosivo/caotico
- punch_moment_s: el segundo exacto donde esta el momento clave del clip
- mejor_rango_s: rango optimo si se tuviera que recortar a lo mejor del clip
- inicio_muerto_s: segundos de inicio que no aportan nada (0 si empieza bien)
- compatibilidad_meme: piensa que memes funcionarian CON este clip como reaccion debajo
"""


def get_tags_by_group():
    """Formatea la taxonomia para el prompt."""
    parts = []
    for group, tags in TAXONOMIA.items():
        parts.append(f"  {group}: {', '.join(tags)}")
    return '\n'.join(parts)


def ensure_clip_columns():
    """Agrega columnas nuevas a la tabla clips si no existen."""
    db = get_db()
    new_columns = [
        ("mood", "TEXT"),
        ("intensidad", "INTEGER"),
        ("audio_analisis", "TEXT"),       # JSON
        ("timing", "TEXT"),               # JSON
        ("recomendaciones", "TEXT"),      # JSON
        ("compatibilidad_meme", "TEXT"),  # JSON array
        ("descripcion_corta", "TEXT"),
        ("categorizado_ia_at", "TIMESTAMP"),
        ("approved", "INTEGER DEFAULT 0"),
    ]
    for col_name, col_type in new_columns:
        try:
            db.execute(f"ALTER TABLE clips ADD COLUMN {col_name} {col_type}")
            db.commit()
        except Exception:
            pass  # Column already exists


def get_pending_clips(force=False, clip_id=None):
    """Obtiene clips aprobados que no han sido categorizados."""
    db = get_db()
    
    if clip_id:
        rows = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchall()
    elif force:
        rows = db.execute("SELECT * FROM clips WHERE COALESCE(approved, 0) = 1").fetchall()
    else:
        rows = db.execute("""
            SELECT * FROM clips 
            WHERE COALESCE(approved, 0) = 1 
            AND categorizado_ia_at IS NULL
        """).fetchall()
    
    return rows


def extract_frames(clip_path, num_frames=5):
    """Extrae N frames equidistantes del video como JPG base64."""
    import base64
    import tempfile
    
    duration = get_video_duration(clip_path)
    if not duration or duration < 1:
        duration = 5.0
    
    frames = []
    # Frames equidistantes (evitar frame 0 que suele ser negro)
    timestamps = [duration * (i + 1) / (num_frames + 1) for i in range(num_frames)]
    
    for ts in timestamps:
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            tmp_path = tmp.name
        
        cmd = [
            'ffmpeg', '-y', '-ss', f'{ts:.2f}',
            '-i', str(clip_path),
            '-vframes', '1', '-q:v', '4',
            '-vf', 'scale=512:-2',
            tmp_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            frames.append({
                'timestamp': round(ts, 1),
                'base64': b64
            })
        
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
    
    return frames


def analyze_clip_with_openai(clip_path, api_key):
    """Analiza clip usando GPT-4o con frames extraidos como imagenes.
    
    Extrae 5 frames equidistantes + envia como imagenes a GPT-4o.
    No analiza audio directamente pero infiere contexto visual.
    """
    import re as _re
    from openai import OpenAI
    
    log = get_logger()
    client = OpenAI(api_key=api_key)
    
    # Step 1: Extract frames
    log.info(f"    Extrayendo frames del video...")
    frames = extract_frames(clip_path, num_frames=5)
    
    if not frames:
        raise RuntimeError("No se pudieron extraer frames del video")
    
    log.info(f"    {len(frames)} frames extraidos. Analizando con GPT-4o...")
    
    # Step 2: Build message with frames
    duration = get_video_duration(clip_path) or 0
    
    frame_descriptions = ", ".join([f"frame@{f['timestamp']}s" for f in frames])
    
    # Build content array with text + images
    content_parts = [
        {
            "type": "text",
            "text": (
                f"Este clip dura {duration:.1f} segundos. "
                f"Te muestro {len(frames)} frames equidistantes ({frame_descriptions}). "
                f"Analiza el clip como si fuera un video de reaccion para TikTok/Reels."
            )
        }
    ]
    
    for frame in frames:
        content_parts.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{frame['base64']}",
                "detail": "low"
            }
        })
    
    # Build prompt
    prompt = CLIP_ANALYSIS_PROMPT.format(tags_by_group=get_tags_by_group())
    
    # Add note about audio limitation
    prompt += """\n\nNOTA IMPORTANTE: No puedes escuchar el audio. Para audio_analisis:
- tipo: inferir del contexto visual (ej: si es video musical = "musica", si hablan = "dialogo")
- descripcion: describir lo que PROBABLEMENTE se escucha basado en el contexto visual
- Los demas campos de audio: dar tu mejor estimacion basada en lo visual
- sirve_como_audio_de_fondo: true si el clip parece tener musica/sonido ambiental util"""
    
    content_parts.append({
        "type": "text",
        "text": prompt
    })
    
    # Step 3: Call GPT-4o with retry
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": content_parts}],
                max_tokens=2000,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            raw_text = response.choices[0].message.content.strip()
            result = json.loads(raw_text)
            
            # Log token usage
            usage = response.usage
            log.info(f"    Tokens: {usage.prompt_tokens} in + {usage.completion_tokens} out = {usage.total_tokens}")
            
            return result
            
        except Exception as e:
            if '429' in str(e) or 'rate' in str(e).lower():
                wait = 20 * (attempt + 1)
                log.warning(f"    Rate limit. Esperando {wait}s... ({attempt+1}/{max_retries})")
                time.sleep(wait)
            elif attempt < max_retries - 1:
                log.warning(f"    Error (intento {attempt+1}): {str(e)[:100]}. Reintentando...")
                time.sleep(3)
            else:
                raise


def analyze_clip_with_gemini(clip_path, api_key):
    """Envia un clip a Gemini 2.0 Flash y obtiene el analisis.
    
    Maneja rate limits respetando el delay sugerido por la API.
    Separa upload de generacion para no re-subir en cada retry.
    """
    import re as _re
    from google import genai
    from google.genai import types
    
    client = genai.Client(api_key=api_key)
    log = get_logger()
    
    # Step 1: Upload video (solo una vez)
    log.info(f"    Subiendo video a Gemini...")
    video_file = client.files.upload(
        file=str(clip_path),
        config=types.UploadFileConfig(mime_type="video/mp4")
    )
    
    # Wait for processing
    max_wait = 120
    waited = 0
    while video_file.state.name == "PROCESSING" and waited < max_wait:
        time.sleep(3)
        waited += 3
        video_file = client.files.get(name=video_file.name)
    
    if video_file.state.name != "ACTIVE":
        raise RuntimeError(f"Video processing failed: state={video_file.state.name}")
    
    log.info(f"    Video listo. Analizando con Flash...")
    
    # Step 2: Generate (con retry respetando rate limits)
    prompt = CLIP_ANALYSIS_PROMPT.format(tags_by_group=get_tags_by_group())
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[video_file, prompt],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    max_output_tokens=2000,
                )
            )
            
            raw_text = response.text.strip()
            
            # Clean up markdown fences
            if raw_text.startswith('```'):
                raw_text = raw_text.split('\n', 1)[1]
                if raw_text.endswith('```'):
                    raw_text = raw_text[:-3].strip()
            
            result = json.loads(raw_text)
            
            # Cleanup uploaded file
            try:
                client.files.delete(name=video_file.name)
            except Exception:
                pass
            
            return result
            
        except Exception as e:
            error_str = str(e)
            
            if '429' in error_str or 'RESOURCE_EXHAUSTED' in error_str:
                # Parse suggested retry delay from error
                delay_match = _re.search(r'retry in ([\d.]+)s', error_str, _re.IGNORECASE)
                if delay_match:
                    wait_time = float(delay_match.group(1)) + 2  # +2s safety margin
                else:
                    wait_time = 30 * (attempt + 1)  # 30s, 60s, 90s...
                
                if attempt < max_retries - 1:
                    log.warning(f"    Rate limit hit. Esperando {wait_time:.0f}s antes de reintentar ({attempt+1}/{max_retries})...")
                    time.sleep(wait_time)
                else:
                    # Cleanup and raise
                    try:
                        client.files.delete(name=video_file.name)
                    except Exception:
                        pass
                    raise RuntimeError(f"Rate limit persistente despues de {max_retries} intentos: {error_str[:200]}")
            else:
                # Non-rate-limit error: cleanup and raise immediately
                try:
                    client.files.delete(name=video_file.name)
                except Exception:
                    pass
                raise


def save_analysis(clip_id, analysis):
    """Guarda el analisis en SQLite."""
    db = get_db()
    
    categorias = json.dumps(analysis.get('categorias', []), ensure_ascii=False)
    audio_analisis = json.dumps(analysis.get('audio_analisis', {}), ensure_ascii=False)
    timing = json.dumps(analysis.get('timing', {}), ensure_ascii=False)
    recomendaciones = json.dumps(analysis.get('recomendaciones', {}), ensure_ascii=False)
    compatibilidad = json.dumps(analysis.get('compatibilidad_meme', []), ensure_ascii=False)
    
    db.execute("""
        UPDATE clips SET
            descripcion = ?,
            descripcion_corta = ?,
            categorias = ?,
            mood = ?,
            intensidad = ?,
            audio_analisis = ?,
            timing = ?,
            recomendaciones = ?,
            compatibilidad_meme = ?,
            categorizado_ia_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (
        analysis.get('descripcion', ''),
        analysis.get('descripcion_corta', ''),
        categorias,
        analysis.get('mood', ''),
        analysis.get('intensidad', 5),
        audio_analisis,
        timing,
        recomendaciones,
        compatibilidad,
        clip_id
    ))
    db.commit()


def print_analysis(clip_id, analysis):
    """Imprime el analisis de forma legible."""
    log = get_logger()
    log.info(f"")
    log.info(f"  {'='*50}")
    log.info(f"  CLIP: {clip_id}")
    log.info(f"  {'='*50}")
    log.info(f"  Descripcion: {analysis.get('descripcion', '?')}")
    log.info(f"  Corta: {analysis.get('descripcion_corta', '?')}")
    log.info(f"  Tags: {', '.join(analysis.get('categorias', []))}")
    log.info(f"  Mood: {analysis.get('mood', '?')} | Intensidad: {analysis.get('intensidad', '?')}/10")
    
    audio = analysis.get('audio_analisis', {})
    log.info(f"  Audio: [{audio.get('tipo', '?')}] {audio.get('descripcion', '?')}")
    log.info(f"         Energia: {audio.get('energia_audio', '?')} | Beat drop: {audio.get('tiene_beat_drop', '?')}")
    
    timing = analysis.get('timing', {})
    log.info(f"  Timing: punch@{timing.get('punch_moment_s', '?')}s | mejor: {timing.get('mejor_rango_s', '?')}")
    if timing.get('inicio_muerto_s', 0) > 0:
        log.info(f"  !! Inicio muerto: {timing['inicio_muerto_s']}s")
    
    recs = analysis.get('recomendaciones', {})
    log.info(f"  Recortar: {recs.get('recortar', 'No')}")
    log.info(f"  Audio original sirve: {recs.get('audio_original_sirve', '?')}")
    if not recs.get('audio_original_sirve', True):
        log.info(f"  Sugerencia audio: {recs.get('audio_sugerencia', '?')}")
    log.info(f"  Meme ideal: {recs.get('meme_ideal', '?')}")
    
    compat = analysis.get('compatibilidad_meme', [])
    log.info(f"  Compatible con: {' | '.join(compat)}")
    log.info(f"")


def main():
    parser = argparse.ArgumentParser(description="Categorizar clips con IA (Gemini o GPT-4o)")
    parser.add_argument('--force', action='store_true', help="Re-categorizar todos (incluso ya categorizados)")
    parser.add_argument('--id', type=str, default=None, help="Categorizar un clip especifico por ID")
    parser.add_argument('--dry-run', action='store_true', help="Solo mostrar que se haria")
    parser.add_argument('--model', type=str, default='gemini', choices=['openai', 'gemini'],
                        help="Motor de IA: 'gemini' (default, video+audio) o 'openai' (GPT-4o frames)")
    args = parser.parse_args()
    
    load_config()
    init_db()
    setup_logger('categorizar_clips')
    log = get_logger()
    
    # Verify API key based on model
    model_choice = args.model
    
    if model_choice == 'gemini':
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            log.error("GOOGLE_API_KEY no encontrada en .env")
            log.error("Obten una en: https://aistudio.google.com/apikey")
            sys.exit(1)
    else:  # openai
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            log.error("OPENAI_API_KEY no encontrada en .env")
            sys.exit(1)
    
    # Pre-load both keys (for potential fallback)
    os.getenv('OPENAI_API_KEY')  # Just verify it exists for fallback
    
    ensure_clip_columns()
    
    clips = get_pending_clips(force=args.force, clip_id=args.id)
    
    if not clips:
        log.info("No hay clips pendientes de categorizar.")
        if not args.force:
            log.info("Usa --force para re-categorizar los ya procesados.")
        return
    
    cost_per_clip = 0.035 if model_choice == 'openai' else 0.001
    model_name = "GPT-4o (frames)" if model_choice == 'openai' else "Gemini 2.0 Flash (video+audio)"
    
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   CATEGORIZAR CLIPS - {model_name}")
    log.info(f"{'='*55}")
    log.info(f"   Clips a procesar: {len(clips)}")
    log.info(f"   Costo estimado:   ~${len(clips) * cost_per_clip:.3f}")
    log.info(f"   Modelo: {model_name}")
    log.info(f"{'='*55}")
    log.info(f"")
    
    if args.dry_run:
        log.info(f"[DRY RUN] Clips que se procesarian ({model_choice}):")
        for clip in clips:
            path = CLIPS_DIR / clip['filename']
            exists = path.exists()
            log.info(f"  {'OK' if exists else 'MISSING'} | {clip['id'][:30]} | {clip['filename']} | {clip['duracion_s']:.1f}s")
        return
    
    # Process clips
    success = 0
    errors = 0
    total_time = 0
    
    for i, clip in enumerate(clips):
        clip_path = CLIPS_DIR / clip['filename']
        
        if not clip_path.exists():
            log.warning(f"  [{i+1}/{len(clips)}] SKIP - archivo no encontrado: {clip['filename']}")
            errors += 1
            continue
        
        log.info(f"  [{i+1}/{len(clips)}] Procesando: {clip['id'][:35]}")
        log.info(f"    Archivo: {clip['filename']} ({clip['duracion_s']:.1f}s)")
        
        start_time = time.time()
        
        try:
            if model_choice == 'gemini':
                analysis = analyze_clip_with_gemini(clip_path, api_key)
            else:
                analysis = analyze_clip_with_openai(clip_path, api_key)
            save_analysis(clip['id'], analysis)
            print_analysis(clip['id'], analysis)
            
            elapsed = time.time() - start_time
            total_time += elapsed
            success += 1
            log.info(f"    OK ({elapsed:.1f}s)")
            
        except json.JSONDecodeError as e:
            log.error(f"    ERROR JSON: {e}")
            errors += 1
            continue
        except Exception as e:
            error_msg = str(e)[:200]
            log.error(f"    ERROR: {error_msg}")
            errors += 1
            
            if 'RESOURCE_EXHAUSTED' in str(e) or '429' in str(e):
                log.warning(f"")
                log.warning(f"    Gemini no disponible (rate limit o billing).")
                
                if model_choice == 'gemini':
                    try:
                        resp = input("    Quieres cambiar a OpenAI GPT-4o? (s/n): ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        resp = 'n'
                    
                    if resp == 's':
                        openai_key = os.getenv('OPENAI_API_KEY')
                        if not openai_key:
                            log.error("    OPENAI_API_KEY no encontrada en .env. Abortando.")
                            break
                        model_choice = 'openai'
                        api_key = openai_key
                        cost_per_clip = 0.035
                        log.info(f"    Cambiando a GPT-4o. Continuando...")
                        continue
                    else:
                        log.info(f"    OK. Abortando.")
                        break
                else:
                    continue
            continue
        
        # Delay between clips (Gemini rate limit: ~15 RPM with billing)
        if i < len(clips) - 1:
            time.sleep(5)
    
    # Summary
    log.info(f"")
    log.info(f"{'='*55}")
    log.info(f"   RESUMEN")
    log.info(f"{'='*55}")
    log.info(f"   Exitosos:     {success}/{len(clips)}")
    log.info(f"   Errores:      {errors}")
    log.info(f"   Tiempo total: {total_time:.1f}s ({total_time/max(success,1):.1f}s promedio)")
    log.info(f"   Costo aprox:  ~${success * cost_per_clip:.4f}")
    log.info(f"{'='*55}")
    
    if success > 0:
        log.info(f"")
        log.info(f"   Siguiente paso:")
        log.info(f"     python catalogo_clips.py --pendientes")
        log.info(f"     (para ver recomendaciones y aplicar cambios)")
        log.info(f"")
        log.info(f"   O directamente al matching:")
        log.info(f"     python 4_match_clip.py")


if __name__ == "__main__":
    main()
