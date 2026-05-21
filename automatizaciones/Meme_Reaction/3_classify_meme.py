#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 3: Clasificación del Meme con IA (OpenAI Vision)

Lee imágenes de memes_descargados/ y las clasifica usando GPT-4o Vision.
Para cada imagen:
  - Verifica si es foto directa o frame de video (desde posts_descargados.json)
  - Envía a OpenAI con contexto apropiado
  - Si es frame de video, la IA puede decir "esto solo tiene sentido como video" -> skip
  - Si es meme válido, categoriza el tipo de humor/remate

Output: historial/clasificaciones.json

Uso:
    python 3_classify_meme.py
    python 3_classify_meme.py --max 10

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
MAX_TOKENS = 600          # Tokens máximos de respuesta

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
    return {"descargados_foto": [], "descargados_frame": [], "skipped_carousels": [], "errores": []}


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
    Envía imagen a OpenAI Vision y obtiene clasificación.
    
    Args:
        client: OpenAI client
        image_path: Path a la imagen
        source_type: 'foto' o 'frame' (determina el prompt)
    
    Returns:
        dict con keys: valido, categoria, confianza, razon, es_video_real
    """
    image_b64 = encode_image_base64(image_path)

    # Prompt según si es foto o frame de video
    if source_type == "frame":
        context_note = """IMPORTANTE: Esta imagen es un SCREENSHOT del primer frame de un video de Instagram.
Muchos de estos videos son simplemente una foto estática con música de fondo (la imagen ES el meme).
Pero algunos son videos reales donde el humor viene del movimiento/acción.

Si la imagen parece un meme completo por sí sola (tiene texto, es una imagen graciosa, etc.), 
clasíficala normalmente.
Si la imagen NO tiene sentido como meme estático (es un frame de acción, alguien hablando, 
una escena que necesita contexto de video), marca como "es_video_real": true."""
    else:
        context_note = "Esta imagen es una foto/post directo de Instagram. Es un meme estático."

    categorias_str = ", ".join(CATEGORIAS)

    prompt = f"""{context_note}

Analiza esta imagen y clasifícala.

Categorías disponibles: {categorias_str}

Responde EXCLUSIVAMENTE en este formato JSON (sin markdown, sin ```):
{{
  "valido": true/false,
  "es_video_real": true/false,
  "categoria": "nombre_categoria",
  "confianza": 0.0-1.0,
  "razon": "breve explicación de por qué esta categoría"
}}

Reglas:
- "valido": false si no es un meme (es publicidad, selfie, paisaje, etc.)
- "es_video_real": true si la imagen claramente es un frame de video que no funciona como meme estático
- Si "valido" es false o "es_video_real" es true, pon categoria como "none"
- "confianza": qué tan seguro estás de la categoría (0.5 = dudoso, 1.0 = obvio)"""

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
        return {"valido": False, "es_video_real": False, "categoria": "none",
                "confianza": 0, "razon": f"Error parseando respuesta: {content[:100]}"}
    except Exception as e:
        return {"valido": False, "es_video_real": False, "categoria": "none",
                "confianza": 0, "razon": f"Error API: {str(e)[:100]}"}


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
    args = parser.parse_args()
    max_sesion = args.max

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 3: CLASIFICACIÓN IA")
    print(SEPARATOR_EQ)
    print(f"   Modelo: {MODEL}")
    print(f"   Máximo por sesión: {max_sesion}")
    print(f"   Carpeta memes: {MEMES_DIR}")

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

    # Obtener imágenes pendientes
    pending = get_pending_images(clasificaciones)
    if not pending:
        print("\n   [!] No hay imágenes pendientes de clasificar.")
        print("       Ejecuta primero: python 2_download_memes.py")
        return

    print(f"   Imágenes pendientes: {len(pending)}")

    # Limitar
    batch = pending[:max_sesion]
    print(f"   Clasificando en esta sesión: {len(batch)}")

    # Crear cliente OpenAI
    client = OpenAI(api_key=api_key)

    # Procesar
    print("")
    print(SEPARATOR)
    print("   CLASIFICANDO...")
    print(SEPARATOR)

    stats = {"clasificados": 0, "video_real": 0, "no_valido": 0, "errores": 0}

    for i, image_path in enumerate(batch):
        shortcode = image_path.stem
        source_type = get_image_source_type(shortcode, downloads_log)
        source_label = "(frame de video)" if source_type == "frame" else "(foto directa)"

        print(f"   [{i+1}/{len(batch)}] {shortcode} {source_label}...", end="")

        result = classify_meme(client, image_path, source_type)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Procesar resultado
        es_video_real = result.get("es_video_real", False)
        valido = result.get("valido", False)
        categoria = result.get("categoria", "none")
        confianza = result.get("confianza", 0)
        razon = result.get("razon", "")

        if es_video_real:
            print(f" -> SKIP (es video real, no meme estático)")
            stats["video_real"] += 1
            clasificaciones["skipped_video_content"].append({
                "shortcode": shortcode,
                "razon": razon,
                "fecha": now,
            })
        elif not valido:
            print(f" -> NO VÁLIDO ({razon[:50]})")
            stats["no_valido"] += 1
            clasificaciones["skipped_video_content"].append({
                "shortcode": shortcode,
                "razon": f"No es meme: {razon}",
                "fecha": now,
            })
        elif categoria == "none" or confianza == 0:
            print(f" -> ERROR ({razon[:50]})")
            stats["errores"] += 1
            clasificaciones["errores"].append({
                "shortcode": shortcode,
                "razon": razon,
                "fecha": now,
            })
        else:
            print(f" -> {categoria} (conf: {confianza})")
            stats["clasificados"] += 1
            clasificaciones["clasificados"].append({
                "shortcode": shortcode,
                "categoria": categoria,
                "confianza": confianza,
                "razon": razon,
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
        print("\n   Distribución:")
        cat_counts = {}
        for item in clasificaciones["clasificados"]:
            cat = item["categoria"]
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"     {cat}: {count}")


if __name__ == "__main__":
    main()
