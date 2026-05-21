#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 3: Clasificación del Meme con IA (OpenAI Vision)

Lee imágenes de memes_descargados/ y las analiza con GPT-4o Vision.
Extrae el máximo de info en UNA sola llamada para no repetir análisis:
  - Validez (es meme o no)
  - Es video real (frame que no funciona solo)
  - Descripción detallada (contexto para caption en paso 6)
  - Categorías (puede ser más de una)
  - Ideas creativas de video (formatos, captions, clips sugeridos)
  - Franjas negras (instrucciones de crop programáticas)
  - Color de fondo (para el video final)
  - Día especial (viernes, halloween, navidad, etc.)

Output: historial/clasificaciones.json

Uso:
    python 3_classify_meme.py
    python 3_classify_meme.py --max 10
    python 3_classify_meme.py --redo ABC123          # Re-clasificar uno específico
    python 3_classify_meme.py --redo ABC123 DEF456   # Re-clasificar varios
    python 3_classify_meme.py --redo-all             # Re-clasificar TODOS

Dependencias: openai, python-dotenv, Pillow
"""

import json
import sys
import time
import random
import argparse
import base64
from pathlib import Path
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    print("   [X] Necesitas instalar openai:")
    print("       pip install openai")
    sys.exit(1)

from dotenv import load_dotenv


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # drako-edits/
HISTORIAL_DIR = SCRIPT_DIR / "historial"
DOWNLOADS_FILE = HISTORIAL_DIR / "posts_descargados.json"
CLASIFICACIONES_FILE = HISTORIAL_DIR / "clasificaciones.json"
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
ENV_FILE = PROJECT_ROOT / ".env"

# --- RATE LIMITING ---
MAX_POR_SESION = 20       # Máximo de imágenes a clasificar por ejecución
DELAY_ENTRE_CALLS = 2     # Segundos entre llamadas a OpenAI

# --- OPENAI ---
MODEL = "gpt-4o"          # Modelo con vision
MAX_TOKENS = 1200         # Tokens máximos de respuesta (más campos = más tokens)

# --- CATEGORIAS ---
CATEGORIAS = [
    "humor_absurdo",
    "humor_dark",
    "cringe",
    "sad_funny",
    "wholesome",
    "plot_twist",
    "relatable",
    "rage",
    "sus",
    "intellectual",
]


# =============================================================================
# FUNCIONES
# =============================================================================

def load_downloads_log():
    """Carga historial de descargas para saber qué es foto vs frame."""
    if DOWNLOADS_FILE.exists():
        try:
            return json.loads(DOWNLOADS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"descargados_foto": [], "descargados_frame": [], "skipped_carousels": [], "skipped_low_likes": [], "errores": []}


def load_clasificaciones():
    """Carga clasificaciones previas."""
    if CLASIFICACIONES_FILE.exists():
        try:
            return json.loads(CLASIFICACIONES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clasificados": [], "skipped_video_content": [], "errores": []}


def save_clasificaciones(data):
    """Guarda clasificaciones."""
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    CLASIFICACIONES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def remove_from_clasificaciones(clasificaciones, shortcodes_to_redo):
    """
    Remueve shortcodes de clasificados/skipped/errores para re-procesarlos.
    Retorna cuantos se removieron.
    """
    removed = 0
    for key in ["clasificados", "skipped_video_content", "errores"]:
        original_len = len(clasificaciones.get(key, []))
        clasificaciones[key] = [
            item for item in clasificaciones.get(key, [])
            if item["shortcode"] not in shortcodes_to_redo
        ]
        removed += original_len - len(clasificaciones[key])
    return removed


def get_image_source_type(shortcode, downloads_log):
    """
    Determina si la imagen es de una foto directa o un frame de video.
    Returns: 'foto' | 'frame' | 'desconocido'
    """
    fotos = [d["shortcode"] for d in downloads_log.get("descargados_foto", [])]
    frames = [d["shortcode"] for d in downloads_log.get("descargados_frame", [])]

    if shortcode in fotos:
        return "foto"
    elif shortcode in frames:
        return "frame"
    return "desconocido"


def encode_image_base64(image_path):
    """Codifica imagen a base64 para enviar a OpenAI."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def classify_meme(client, image_path, source_type):
    """
    Envía imagen a OpenAI Vision y obtiene análisis completo.
    Extrae TODO en una sola llamada para no repetir (costo de imagen es fijo).
    """
    image_b64 = encode_image_base64(image_path)

    # Prompt según si es foto o frame de video
    if source_type == "frame":
        context_note = """IMPORTANTE: Esta imagen es un SCREENSHOT del primer frame de un video de Instagram.
Muchos de estos videos son simplemente una foto estática con música de fondo (la imagen ES el meme).
Pero algunos son videos reales donde el humor viene del movimiento/acción.

Si la imagen parece un meme completo por sí sola (tiene texto, es una imagen graciosa, etc.),
analízala normalmente.
Si la imagen NO tiene sentido como meme estático (es un frame de acción, alguien hablando,
una escena que necesita contexto de video), marca "es_video_real": true."""
    else:
        context_note = "Esta imagen es una foto/post directo de Instagram. Es un meme estático."

    categorias_str = ", ".join(CATEGORIAS)

    prompt = f"""{context_note}

Analiza esta imagen a fondo. Necesito TODA la info posible en UNA sola llamada.
Este análisis se usará para generar un video de "meme reaction" (meme arriba + clip de reacción abajo).

Categorías disponibles: {categorias_str}

Responde EXCLUSIVAMENTE en este formato JSON (sin markdown, sin ```):
{{
  "valido": true/false,
  "es_video_real": true/false,
  "categorias": ["cat1", "cat2"],
  "confianza": 0.0-1.0,
  "descripcion": "Descripción detallada del meme: qué muestra, qué texto tiene, cuál es el chiste/remate. Escríbela como si alguien que NO ve la imagen pudiera entender el humor completamente.",
  "ideas_video": [
    {{
      "formato": "meme_arriba_clip_abajo" | "dos_videos_paralelos" | "meme_con_caption_y_clip" | "otro",
      "caption_sugerido": "texto corto para poner encima del video, o null si no necesita",
      "clip_ideal": "descripción del tipo de clip que quedaría bien abajo (ej: 'persona riéndose sin control', 'alguien comiendo palomitas tipo Michael Jackson', 'persona asintiendo con cara de orgullo')",
      "descripcion_idea": "breve explicación de por qué esta combinación funcionaría"
    }}
  ],
  "background_color": "negro" | "blanco" | "otro",
  "franjas_negras": {{
    "tiene": true/false,
    "arriba": 0.0-1.0,
    "abajo": 0.0-1.0,
    "crop_arriba": true/false,
    "crop_abajo": true/false
  }},
  "dia_especial": null | "viernes" | "lunes" | "halloween" | "navidad" | "fin_de_ano" | "san_valentin" | "otro: [cual]"
}}

Reglas:
- "valido": false si no es un meme (es publicidad, selfie, paisaje, promoción, etc.)
- "es_video_real": true si la imagen claramente es un frame de video que no funciona como meme estático
- Si "valido" es false o "es_video_real" es true, pon categorias como [], ideas_video como [], y descripcion breve
- "categorias": puede tener 1 a 3 categorías que apliquen (de más relevante a menos)
- "confianza": qué tan seguro estás de la clasificación (0.5 = dudoso, 1.0 = obvio)
- "descripcion": DETALLADA. Incluye texto visible exacto, contexto cultural, el remate. Es para que otro modelo genere un caption SIN ver la imagen.
- "ideas_video": genera 2-3 ideas creativas de cómo usar este meme en un video corto. Piensa en formatos virales de TikTok/Reels. Puedes sugerir:
  * Formatos alternativos (split screen con 2 clips, meme + reacción clásica, etc.)
  * Clips específicos populares que quedarían bien (ej: "Michael Jackson comiendo palomitas", "gato mirando fijo", "persona llorando de risa")
  * Captions que le añadan humor al video
  * Si el meme tiene estructura "X / Yo:" sugiere split con el contraste
- "background_color": el color predominante del fondo del meme (para elegir fondo del video final)
- "franjas_negras": MIRA CON CUIDADO los bordes de la imagen. Detecta bandas/barras/padding de color sólido (generalmente negro pero puede ser de otro color oscuro) arriba y/o abajo que NO son parte del contenido del meme.
  * "tiene": true si hay AL MENOS una franja arriba O abajo. Mira los pixeles de los bordes superior e inferior.
  * "arriba": porcentaje de la imagen que es franja ARRIBA (0.0 si no hay). Ej: si el 15% superior es barra negra = 0.15. SE PRECISO, mide visualmente.
  * "abajo": porcentaje de la imagen que es franja ABAJO (0.0 si no hay). Ej: si el 10% inferior es barra negra = 0.10. SE PRECISO, mide visualmente.
  * "crop_arriba": true si la franja de arriba se puede cortar SIN perder texto ni contenido importante. false si hay texto/watermark en la franja.
  * "crop_abajo": true si la franja de abajo se puede cortar SIN perder texto ni contenido importante. false si hay texto/watermark en la franja.
  * IMPORTANTE: Si la imagen TIENE franjas visibles, "tiene" DEBE ser true y los valores de arriba/abajo DEBEN reflejar el porcentaje real. No pongas 0.0 si ves una franja.
  * Evalúa arriba y abajo POR SEPARADO. Puede haber texto arriba pero no abajo.
- "dia_especial": si el meme SOLO tiene sentido en un día/fecha específica. Analiza el contexto completo:
  * "día 31" + "todo el año" = fin_de_ano (NO halloween)
  * "es viernes" = viernes
  * Escenas navideñas = navidad
  * null si es atemporal (publicar cualquier día)"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "low"
                            }
                        }
                    ]
                }
            ]
        )

        # Parsear respuesta
        content = response.choices[0].message.content.strip()
        # Limpiar si viene con ``` markdown
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)
        return result

    except json.JSONDecodeError:
        return {"valido": False, "es_video_real": False, "categorias": [], "confianza": 0,
                "descripcion": "", "ideas_video": [], "background_color": "otro",
                "franjas_negras": {"tiene": False, "arriba": 0, "abajo": 0, "crop_arriba": False, "crop_abajo": False},
                "dia_especial": None,
                "_error": f"Error parseando respuesta: {content[:200]}"}
    except Exception as e:
        return {"valido": False, "es_video_real": False, "categorias": [], "confianza": 0,
                "descripcion": "", "ideas_video": [], "background_color": "otro",
                "franjas_negras": {"tiene": False, "arriba": 0, "abajo": 0, "crop_arriba": False, "crop_abajo": False},
                "dia_especial": None,
                "_error": f"Error API: {str(e)[:200]}"}


def get_pending_images(clasificaciones):
    """
    Obtiene imágenes en memes_descargados/ que aún no han sido clasificadas.
    """
    if not MEMES_DIR.exists():
        return []

    # Shortcodes ya clasificados
    ya_clasificados = set()
    for item in clasificaciones.get("clasificados", []):
        ya_clasificados.add(item["shortcode"])
    for item in clasificaciones.get("skipped_video_content", []):
        ya_clasificados.add(item["shortcode"])
    for item in clasificaciones.get("errores", []):
        ya_clasificados.add(item["shortcode"])

    # Buscar imágenes no clasificadas
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp'}
    pending = []
    for f in sorted(MEMES_DIR.iterdir()):
        if f.suffix.lower() in image_extensions:
            shortcode = f.stem
            if shortcode not in ya_clasificados:
                pending.append(f)

    return pending


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def main():
    parser = argparse.ArgumentParser(description="Paso 3: Clasificar memes con IA")
    parser.add_argument("--max", type=int, default=MAX_POR_SESION,
                        help=f"Máximo de imágenes a clasificar (default: {MAX_POR_SESION})")
    parser.add_argument("--redo", nargs="+", metavar="SHORTCODE",
                        help="Re-clasificar shortcodes específicos (los remueve de clasificados y re-procesa)")
    parser.add_argument("--redo-all", action="store_true",
                        help="Re-clasificar TODOS los memes (borra clasificaciones y re-procesa)")
    args = parser.parse_args()
    max_sesion = args.max

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 3: ANÁLISIS IA COMPLETO")
    print(SEPARATOR_EQ)
    print(f"   Modelo: {MODEL}")
    print(f"   Máximo por sesión: {max_sesion}")
    print(f"   Carpeta memes: {MEMES_DIR}")
    print("")
    print("   Extrae por imagen:")
    print("     - Validez + es_video_real")
    print("     - Categorías (1-3)")
    print("     - Descripción detallada (para caption)")
    print("     - Ideas de video (2-3 ideas creativas)")
    print("     - Franjas negras (crop por separado arriba/abajo)")
    print("     - Background color")
    print("     - Día especial (viernes, fin_de_ano, etc.)")

    # Cargar .env
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
        print(f"   .env cargado: {ENV_FILE}")
    else:
        print(f"   [!] No se encontró .env en: {ENV_FILE}")

    # Verificar API key
    import os
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("\n   [X] OPENAI_API_KEY no configurada en .env")
        return
    print("   OpenAI API key: ..." + api_key[-4:])

    # Cargar datos
    downloads_log = load_downloads_log()
    clasificaciones = load_clasificaciones()

    # --- REDO: remover de clasificados para re-procesar ---
    if args.redo_all:
        total_prev = len(clasificaciones.get("clasificados", []))
        clasificaciones["clasificados"] = []
        clasificaciones["skipped_video_content"] = []
        clasificaciones["errores"] = []
        save_clasificaciones(clasificaciones)
        print(f"\n   [REDO-ALL] Eliminadas {total_prev} clasificaciones. Re-procesando todo.")

    elif args.redo:
        shortcodes_to_redo = set(args.redo)
        removed = remove_from_clasificaciones(clasificaciones, shortcodes_to_redo)
        save_clasificaciones(clasificaciones)
        if removed > 0:
            print(f"\n   [REDO] Removidos {removed} entries para re-clasificar: {', '.join(args.redo)}")
        else:
            print(f"\n   [REDO] Shortcodes no encontrados en clasificaciones: {', '.join(args.redo)}")
            print(f"          (puede que ya estén pendientes)")

    # Obtener imágenes pendientes
    pending = get_pending_images(clasificaciones)
    if not pending:
        print("\n   [!] No hay imágenes pendientes de clasificar.")
        print("       Ejecuta primero: python 2_download_memes.py")
        return

    print(f"   Imágenes pendientes: {len(pending)}")

    # Si es --redo, filtrar solo los que pidió
    if args.redo:
        redo_set = set(args.redo)
        pending = [p for p in pending if p.stem in redo_set]
        if not pending:
            print(f"\n   [!] Las imágenes de --redo no existen en memes_descargados/")
            return
        print(f"   Re-clasificando: {len(pending)} (--redo)")

    # Limitar
    batch = pending[:max_sesion]
    print(f"   Clasificando en esta sesión: {len(batch)}")

    # Crear cliente OpenAI
    client = OpenAI(api_key=api_key)

    # Procesar
    print("")
    print(SEPARATOR)
    print("   ANALIZANDO...")
    print(SEPARATOR)

    stats = {"clasificados": 0, "video_real": 0, "no_valido": 0, "errores": 0}

    for i, image_path in enumerate(batch):
        shortcode = image_path.stem
        source_type = get_image_source_type(shortcode, downloads_log)
        source_label = "(frame)" if source_type == "frame" else "(foto)"

        print(f"   [{i+1}/{len(batch)}] {shortcode} {source_label}...", end="")

        result = classify_meme(client, image_path, source_type)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Procesar resultado
        es_video_real = result.get("es_video_real", False)
        valido = result.get("valido", False)
        categorias = result.get("categorias", [])
        confianza = result.get("confianza", 0)
        descripcion = result.get("descripcion", "")
        ideas_video = result.get("ideas_video", [])
        background_color = result.get("background_color", "otro")
        franjas_negras = result.get("franjas_negras", {"tiene": False, "arriba": 0, "abajo": 0, "crop_arriba": False, "crop_abajo": False})
        dia_especial = result.get("dia_especial", None)
        error_msg = result.get("_error", "")

        if error_msg:
            print(f" -> ERROR ({error_msg[:40]})")
            stats["errores"] += 1
            clasificaciones["errores"].append({
                "shortcode": shortcode,
                "error": error_msg,
                "fecha": now,
            })
        elif es_video_real:
            print(f" -> SKIP (video real)")
            stats["video_real"] += 1
            clasificaciones["skipped_video_content"].append({
                "shortcode": shortcode,
                "descripcion": descripcion,
                "fecha": now,
            })
        elif not valido:
            print(f" -> NO VALIDO")
            stats["no_valido"] += 1
            clasificaciones["skipped_video_content"].append({
                "shortcode": shortcode,
                "descripcion": f"No es meme: {descripcion}",
                "fecha": now,
            })
        elif not categorias or confianza == 0:
            print(f" -> ERROR (sin categorías)")
            stats["errores"] += 1
            clasificaciones["errores"].append({
                "shortcode": shortcode,
                "error": "Sin categorías asignadas",
                "fecha": now,
            })
        else:
            cats_str = ", ".join(categorias)
            n_ideas = len(ideas_video)
            dia_str = f" [{dia_especial}]" if dia_especial else ""
            franjas_str = ""
            if franjas_negras.get("tiene"):
                f_arr = franjas_negras.get('arriba', 0)
                f_abj = franjas_negras.get('abajo', 0)
                franjas_str = f" [franjas: arr={f_arr:.0%} abj={f_abj:.0%}]"
            print(f" -> {cats_str} ({n_ideas} ideas){dia_str}{franjas_str}")
            stats["clasificados"] += 1
            clasificaciones["clasificados"].append({
                "shortcode": shortcode,
                "categorias": categorias,
                "confianza": confianza,
                "descripcion": descripcion,
                "ideas_video": ideas_video,
                "background_color": background_color,
                "franjas_negras": franjas_negras,
                "dia_especial": dia_especial,
                "source_type": source_type,
                "fecha": now,
            })

        # Guardar progreso después de cada clasificación (por si se interrumpe)
        save_clasificaciones(clasificaciones)

        # Delay
        if i < len(batch) - 1:
            time.sleep(DELAY_ENTRE_CALLS + random.uniform(0, 1))

    # Resumen
    print("")
    print(SEPARATOR_EQ)
    print("   RESUMEN")
    print(SEPARATOR_EQ)
    print(f"   Memes clasificados: {stats['clasificados']}")
    print(f"   Skipped (video real): {stats['video_real']}")
    print(f"   No válidos (no meme): {stats['no_valido']}")
    print(f"   Errores: {stats['errores']}")
    print(f"   Pendientes restantes: {len(pending) - len(batch)}")
    print(f"   Guardado en: {CLASIFICACIONES_FILE}")
    print(SEPARATOR_EQ)

    # Mostrar distribución de categorías
    if stats["clasificados"] > 0:
        print("\n   Distribución de categorías:")
        cat_counts = {}
        for item in clasificaciones["clasificados"]:
            for cat in item.get("categorias", []):
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"     {cat}: {count}")

        # Mostrar dias especiales si hay
        dias = [item["dia_especial"] for item in clasificaciones["clasificados"] if item.get("dia_especial")]
        if dias:
            print("\n   Memes con día especial:")
            for dia in set(dias):
                count = dias.count(dia)
                print(f"     {dia}: {count}")


if __name__ == "__main__":
    main()
