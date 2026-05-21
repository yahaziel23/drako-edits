#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 4: Match Meme con Clip de Reaccion (interactivo + IA conversacional)

Para cada meme clasificado (paso 3), la IA:
  1. Revisa el catalogo de clips disponibles
  2. Elige el mejor match y da un % de que tan bien queda
  3. Sugiere que clip IDEAL necesitarias (con ejemplos virales)
  4. Sugiere caption (o dice que no necesita)
  5. TU decides: usar ese clip, sugerir otro, o skip

Opcion 'r' (responder): conversacion con la IA.
  - Le dices que clip crees que queda y con que caption
  - La IA evalua tu idea, da accuracy %, sugiere ajustes
  - Puedes iterar hasta que quede

Uso:
    python 4_match_clip.py
    python 4_match_clip.py --max 5

Dependencias: openai, python-dotenv
"""

import json
import sys
import os
import argparse
import time
import random
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
PROJECT_ROOT = SCRIPT_DIR.parent.parent
HISTORIAL_DIR = SCRIPT_DIR / "historial"
CLASIFICACIONES_FILE = HISTORIAL_DIR / "clasificaciones.json"
MATCHES_FILE = HISTORIAL_DIR / "matches.json"
CATALOGO_FILE = SCRIPT_DIR / "catalogo_clips.json"
CLIPS_DIR = SCRIPT_DIR / "clips"
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
ENV_FILE = PROJECT_ROOT / ".env"

MODEL = "gpt-4o-mini"  # Texto puro, barato
MAX_POR_SESION = 10


# =============================================================================
# FUNCIONES - CARGA DE DATOS
# =============================================================================

def load_clasificaciones():
    if CLASIFICACIONES_FILE.exists():
        try:
            return json.loads(CLASIFICACIONES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clasificados": [], "skipped_video_content": [], "errores": []}


def load_catalogo():
    if CATALOGO_FILE.exists():
        try:
            return json.loads(CATALOGO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clips": []}


def load_matches():
    if MATCHES_FILE.exists():
        try:
            return json.loads(MATCHES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"matched": [], "skipped_buscar_clip": []}


def save_matches(data):
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    MATCHES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_pending_memes(clasificaciones, matches):
    """Memes clasificados que aun no tienen match ni skip."""
    already = set()
    for item in matches.get("matched", []):
        already.add(item["shortcode"])
    for item in matches.get("skipped_buscar_clip", []):
        already.add(item["shortcode"])

    pending = []
    for item in clasificaciones.get("clasificados", []):
        if item["shortcode"] not in already:
            img_path = MEMES_DIR / f"{item['shortcode']}.jpg"
            if img_path.exists():
                pending.append(item)
    return pending


# =============================================================================
# FUNCIONES - IA (MATCH)
# =============================================================================

def build_catalogo_text(catalogo):
    """Construye texto del catalogo para el prompt."""
    if not catalogo.get("clips"):
        return "(CATALOGO VACIO - no hay clips disponibles)"

    lines = []
    for clip in catalogo["clips"]:
        cats = ", ".join(clip.get("categorias", []))
        used = clip.get("usado_count", 0)
        lines.append(f"- ID: {clip['id']} | Cats: [{cats}] | Desc: \"{clip['descripcion']}\" | Usado: {used}x")
    return "\n".join(lines)


CLIP_IDEAL_RULE = 'Para clip_ideal: se ESPECIFICO. No digas "alguien riendo", di "el clip viral de [persona/personaje] haciendo [cosa especifica]"'


def match_meme_with_clips(client, meme_data, catalogo_text):
    """
    La IA analiza el meme y sugiere el mejor clip del catalogo.
    Retorna la respuesta como dict.
    """
    categorias = ", ".join(meme_data.get("categorias", []))
    descripcion = meme_data.get("descripcion", "")
    ideas = meme_data.get("ideas_video", [])

    ideas_text = ""
    if ideas:
        ideas_lines = []
        for i, idea in enumerate(ideas, 1):
            cap = idea.get('caption_sugerido', 'ninguno')
            clip = idea.get('clip_ideal', '?')
            fmt = idea.get('formato', '?')
            ideas_lines.append(f"  Idea {i}: formato={fmt}, caption=\"{cap}\", clip_ideal=\"{clip}\"")
        ideas_text = "\n".join(ideas_lines)

    prompt = f"""Eres un experto en contenido viral de memes/reels. Tu trabajo es hacer match entre un meme y un clip de reaccion para crear un video corto tipo meme reaction.

MEME A MATCHEAR:
- Categorias: {categorias}
- Descripcion: "{descripcion}"
- Ideas previas del analisis:
{ideas_text}

CATALOGO DE CLIPS DISPONIBLES:
{catalogo_text}

Tu tarea:
1. MEJOR MATCH: Elige el clip del catalogo que MEJOR queda con este meme. Da un porcentaje de que tan bien queda (0-100%). Se HONESTO - si ninguno queda bien, dilo.

2. CAPTION: El video necesita un caption superpuesto? Si el meme habla por si solo, di sin caption. Si si necesita, sugiere uno corto (max 2 lineas). El caption debe anadir humor, no repetir lo que ya dice el meme.

3. CLIP IDEAL: Describe que clip seria PERFECTO para este meme (aunque no este en el catalogo). Da ejemplos concretos y virales.

4. IDEAS ALTERNATIVAS: Si se te ocurren otros formatos creativos (split screen, otro clip, otro caption), mencionalos brevemente.

Responde en este formato JSON (sin markdown, sin ```):
{{
  "mejor_match": {{
    "clip_id": "id_del_clip" | null,
    "accuracy": 0-100,
    "razon": "por que este clip queda (o no queda)"
  }},
  "caption": null | "texto del caption",
  "clip_ideal": "descripcion del clip perfecto con ejemplo viral concreto",
  "ideas_alternativas": [
    "idea 1 breve",
    "idea 2 breve"
  ]
}}

REGLAS:
- Si el catalogo esta vacio o ningun clip queda arriba de 40%, pon clip_id: null
- accuracy < 40% = no vale la pena, mejor buscar otro
- accuracy 40-70% = funciona pero no es ideal
- accuracy > 70% = buen match
- Para caption: piensa si REALMENTE anade algo. Muchos memes son mejores sin caption.
- {CLIP_IDEAL_RULE}
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        return json.loads(content)
    except json.JSONDecodeError:
        return {"mejor_match": {"clip_id": None, "accuracy": 0, "razon": f"Error parseando: {content[:100]}"},
                "caption": None, "clip_ideal": "Error", "ideas_alternativas": []}
    except Exception as e:
        return {"mejor_match": {"clip_id": None, "accuracy": 0, "razon": f"Error API: {str(e)[:100]}"},
                "caption": None, "clip_ideal": "Error", "ideas_alternativas": []}


def chat_evaluate_suggestion(client, meme_data, catalogo_text, conversation_history, user_suggestion):
    """
    Conversacion con la IA: el usuario sugiere un clip/caption y la IA evalua.
    Mantiene historial de la conversacion para contexto.
    Retorna (respuesta_texto, resultado_json_o_None).
    """
    categorias = ", ".join(meme_data.get("categorias", []))
    descripcion = meme_data.get("descripcion", "")

    system_msg = f"""Eres un experto en contenido viral de memes/reels. Estas en una conversacion con el creador sobre que clip de reaccion usar para un meme.

CONTEXTO DEL MEME:
- Categorias: {categorias}
- Descripcion: "{descripcion}"

CATALOGO DE CLIPS DISPONIBLES:
{catalogo_text}

Tu rol en la conversacion:
- El usuario te sugiere clips y/o captions que cree que quedan
- Tu evaluas honestamente: da un % de accuracy y di por que si o por que no
- Si la idea es buena, dilo. Si se puede mejorar, sugiere como
- Si el clip que menciona esta en el catalogo, referencialo por ID
- Si no esta, di que clip habria que buscar/descargar
- Se directo y conciso, no repitas info que ya diste
- Puedes sugerir ajustes al caption, o decir que no necesita

Cuando el usuario diga que quiere FINALIZAR o que le convencio una opcion, responde en este formato JSON (sin markdown):
{{
  "decision": "aceptar",
  "clip_id": "id_del_clip" | null,
  "clip_descripcion": "descripcion del clip elegido (si no esta en catalogo)",
  "accuracy": 0-100,
  "caption": null | "texto del caption",
  "razon": "por que esta combinacion funciona"
}}

Si NO es momento de finalizar (siguen conversando), responde en texto normal (NO JSON)."""

    messages = [{"role": "system", "content": system_msg}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_suggestion})

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=400,
            messages=messages
        )
        content = response.choices[0].message.content.strip()

        # Intentar parsear como JSON (la IA decidio finalizar)
        try:
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            result = json.loads(content)
            if "decision" in result:
                return content, result
        except (json.JSONDecodeError, ValueError):
            pass

        # Es texto normal (siguen conversando)
        return content, None

    except Exception as e:
        return f"[Error IA: {str(e)[:100]}]", None


# =============================================================================
# FUNCIONES - DISPLAY
# =============================================================================

def open_image(image_path):
    try:
        if sys.platform == "win32":
            os.startfile(str(image_path))
        elif sys.platform == "darwin":
            os.system(f'open "{image_path}"')
        else:
            os.system(f'xdg-open "{image_path}"')
    except Exception:
        pass


def display_match_result(result, meme_data, catalogo):
    """Muestra el resultado del match de forma legible."""
    match = result.get("mejor_match", {})
    clip_id = match.get("clip_id")
    accuracy = match.get("accuracy", 0)
    razon = match.get("razon", "")
    caption = result.get("caption")
    clip_ideal = result.get("clip_ideal", "")
    ideas = result.get("ideas_alternativas", [])

    print(f"")
    print(f"       MEJOR MATCH DEL CATALOGO:")
    if clip_id:
        clip_info = next((c for c in catalogo.get("clips", []) if c["id"] == clip_id), None)
        clip_desc = clip_info["descripcion"] if clip_info else "?"
        bar = "#" * (accuracy // 5) + "-" * (20 - accuracy // 5)
        print(f"         Clip: {clip_id}")
        print(f"         Desc: \"{clip_desc}\"")
        print(f"         Accuracy: [{bar}] {accuracy}%")
        print(f"         Razon: {razon}")
    else:
        print(f"         (Ningun clip del catalogo queda bien)")
        print(f"         Razon: {razon}")

    print(f"")
    print(f"       CAPTION SUGERIDO:")
    if caption:
        print(f"         \"{caption}\"")
    else:
        print(f"         (sin caption - el meme habla solo)")

    print(f"")
    print(f"       CLIP IDEAL (lo que DEBERIA ser):")
    print(f"         {clip_ideal}")

    if ideas:
        print(f"")
        print(f"       IDEAS ALTERNATIVAS:")
        for i, idea in enumerate(ideas, 1):
            print(f"         {i}. {idea}")


def display_chat_response(response_text):
    """Muestra la respuesta de la IA en la conversacion."""
    print(f"")
    print(f"       IA:")
    for line in response_text.split("\n"):
        print(f"         {line}")
    print(f"")


# =============================================================================
# FUNCIONES - INTERACCION CONVERSACIONAL
# =============================================================================

def run_conversation(client, meme_data, catalogo_text, catalogo, shortcode):
    """
    Loop conversacional: el usuario sugiere clips/captions, la IA evalua.
    Retorna match_entry dict si se acepta, o None si se sale.
    """
    print(f"")
    print(f"       --- MODO CONVERSACION ---")
    print(f"       Dile a la IA que clip/caption crees que queda.")
    print(f"       Ejemplos:")
    print(f"         'creo que el de pedro pascal llorando con caption como me gano la vida'")
    print(f"         'y si usamos clip_01 pero sin caption?'")
    print(f"         'que tal uno de alguien asintiendo tipo el viejito del slow clap'")
    print(f"       Comandos: 'ok'/'listo' = aceptar ultima idea | 'salir' = volver al menu")
    print(f"       {'─' * 50}")

    conversation_history = []
    last_result = None

    while True:
        user_input = input("       Tu: ").strip()

        if not user_input:
            continue

        if user_input.lower() in ('salir', 'back', 'volver', 'x'):
            print("       (Volviendo al menu principal)")
            return None, "back"

        # Si dice ok/listo, pedir a la IA que formalice la ultima idea
        if user_input.lower() in ('ok', 'listo', 'dale', 'va', 'esa'):
            if last_result:
                return last_result, "accept"
            else:
                # Forzar finalizacion
                user_input = "Listo, me convencio la ultima opcion que discutimos. Dame el JSON final."

        # Agregar al historial y enviar
        conversation_history.append({"role": "user", "content": user_input})
        print("       ...")

        response_text, result_json = chat_evaluate_suggestion(
            client, meme_data, catalogo_text, conversation_history, user_input
        )

        # Quitar el ultimo user msg (ya lo agregamos antes) y agregar el de la IA
        conversation_history.pop()
        conversation_history.append({"role": "user", "content": user_input})
        conversation_history.append({"role": "assistant", "content": response_text})

        if result_json and "decision" in result_json:
            # La IA devolvio JSON = finalizacion
            clip_id = result_json.get("clip_id")
            accuracy = result_json.get("accuracy", 0)
            caption = result_json.get("caption")
            razon = result_json.get("razon", "")
            clip_desc = result_json.get("clip_descripcion", "")

            print(f"")
            print(f"       IA FINALIZO:")
            if clip_id:
                bar = "#" * (accuracy // 5) + "-" * (20 - accuracy // 5)
                print(f"         Clip: {clip_id}")
                print(f"         Accuracy: [{bar}] {accuracy}%")
            else:
                print(f"         Clip (no en catalogo): {clip_desc}")
                print(f"         Accuracy estimada: {accuracy}%")
            if caption:
                print(f"         Caption: \"{caption}\"")
            else:
                print(f"         Caption: (sin caption)")
            print(f"         Razon: {razon}")

            last_result = {
                "shortcode": shortcode,
                "clip_id": clip_id,
                "accuracy": accuracy,
                "caption": caption,
                "clip_ideal_sugerido": clip_desc or razon,
                "conversacion": True,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # Preguntar si acepta
            print(f"")
            confirm = input("       Aceptar esto? (Enter/s=si, seguir hablando=cualquier texto): ").strip()
            if confirm.lower() in ('', 's', 'si', 'ok', 'dale'):
                return last_result, "accept"
            else:
                # Seguir conversando con el nuevo input
                conversation_history.append({"role": "user", "content": confirm})
                print("       ...")
                resp2, res2 = chat_evaluate_suggestion(
                    client, meme_data, catalogo_text, conversation_history, confirm
                )
                conversation_history.pop()
                conversation_history.append({"role": "user", "content": confirm})
                conversation_history.append({"role": "assistant", "content": resp2})
                display_chat_response(resp2)
                if res2 and "decision" in res2:
                    last_result = {
                        "shortcode": shortcode,
                        "clip_id": res2.get("clip_id"),
                        "accuracy": res2.get("accuracy", 0),
                        "caption": res2.get("caption"),
                        "clip_ideal_sugerido": res2.get("clip_descripcion", ""),
                        "conversacion": True,
                        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
        else:
            # Respuesta normal (texto), seguir conversando
            display_chat_response(response_text)


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def accept_match(result, shortcode, catalogo):
    """Construye match_entry y actualiza usado_count."""
    match_entry = {
        "shortcode": shortcode,
        "clip_id": result.get("mejor_match", {}).get("clip_id"),
        "accuracy": result.get("mejor_match", {}).get("accuracy", 0),
        "caption": result.get("caption"),
        "clip_ideal_sugerido": result.get("clip_ideal", ""),
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    clip_id = match_entry["clip_id"]
    if clip_id:
        for clip in catalogo.get("clips", []):
            if clip["id"] == clip_id:
                clip["usado_count"] = clip.get("usado_count", 0) + 1
                break
        CATALOGO_FILE.write_text(
            json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return match_entry


def main():
    parser = argparse.ArgumentParser(description="Paso 4: Match meme con clip")
    parser.add_argument("--max", type=int, default=MAX_POR_SESION,
                        help=f"Maximo de memes a matchear (default: {MAX_POR_SESION})")
    args = parser.parse_args()

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 4: MATCH CON CLIP (INTERACTIVO)")
    print(SEPARATOR_EQ)
    print("   La IA sugiere el mejor clip + caption.")
    print("   TU decides si lo aceptas o propones algo mejor.")
    print("")
    print("   Controles por meme:")
    print("     s / Enter = ACEPTAR match (clip + caption de la IA)")
    print("     c         = Cambiar caption (acepto clip pero no el caption)")
    print("     r         = RESPONDER - conversar con IA (sugerir clip/caption)")
    print("     n         = NO me convence, SKIP (buscare clip despues)")
    print("     q         = SALIR")
    print(SEPARATOR_EQ)

    # Cargar .env
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\n   [X] OPENAI_API_KEY no configurada")
        return

    # Cargar datos
    clasificaciones = load_clasificaciones()
    catalogo = load_catalogo()
    matches = load_matches()

    n_clips = len(catalogo.get("clips", []))
    print(f"   Clips en catalogo: {n_clips}")

    if n_clips == 0:
        print("   [!] Catalogo vacio. La IA sugerira clips ideales pero no podra hacer match.")
        print("       Corre: python catalogar_clips.py")

    # Obtener pendientes
    pending = get_pending_memes(clasificaciones, matches)
    if not pending:
        print("\n   [!] No hay memes pendientes de match.")
        print(f"       Matched: {len(matches.get('matched', []))} | Skipped: {len(matches.get('skipped_buscar_clip', []))}")
        return

    batch = pending[:args.max]
    print(f"   Memes pendientes: {len(pending)}")
    print(f"   Procesando: {len(batch)}")

    # Crear cliente
    client = OpenAI(api_key=api_key)
    catalogo_text = build_catalogo_text(catalogo)

    # Loop
    stats = {"matched": 0, "skipped": 0}

    for i, meme_data in enumerate(batch):
        shortcode = meme_data["shortcode"]
        cats = ", ".join(meme_data.get("categorias", []))
        img_path = MEMES_DIR / f"{shortcode}.jpg"

        print(f"\n{SEPARATOR}")
        print(f"   [{i+1}/{len(batch)}] {shortcode}")
        print(f"       Categorias: {cats}")
        desc = meme_data.get("descripcion", "")[:120]
        print(f"       Desc: {desc}...")
        print(SEPARATOR)

        # Abrir imagen
        if img_path.exists():
            open_image(img_path)

        # IA Match
        print("       Analizando con IA...")
        result = match_meme_with_clips(client, meme_data, catalogo_text)
        display_match_result(result, meme_data, catalogo)

        # Decision del usuario
        print(f"\n{SEPARATOR}")
        while True:
            choice = input("       Que hacer? (s/Enter=aceptar, c=caption, r=responder IA, n=skip, q=salir): ").strip().lower()

            if choice in ("", "s", "si"):
                # Aceptar match de la IA
                match_entry = accept_match(result, shortcode, catalogo)
                matches["matched"].append(match_entry)
                save_matches(matches)
                stats["matched"] += 1
                print("       -> MATCH ACEPTADO")
                break

            elif choice == 'c':
                # Cambiar caption
                new_caption = input("       Nuevo caption (vacio = sin caption): ").strip()
                caption_final = new_caption if new_caption else None

                match_entry = accept_match(result, shortcode, catalogo)
                match_entry["caption"] = caption_final
                matches["matched"].append(match_entry)
                save_matches(matches)
                stats["matched"] += 1
                print(f"       -> MATCH ACEPTADO (caption cambiado)")
                break

            elif choice == 'r':
                # Conversacion con la IA
                conv_result, action = run_conversation(
                    client, meme_data, catalogo_text, catalogo, shortcode
                )

                if action == "accept" and conv_result:
                    # Actualizar usado_count si el clip esta en catalogo
                    clip_id = conv_result.get("clip_id")
                    if clip_id:
                        for clip in catalogo.get("clips", []):
                            if clip["id"] == clip_id:
                                clip["usado_count"] = clip.get("usado_count", 0) + 1
                                break
                        CATALOGO_FILE.write_text(
                            json.dumps(catalogo, ensure_ascii=False, indent=2), encoding="utf-8"
                        )

                    matches["matched"].append(conv_result)
                    save_matches(matches)
                    stats["matched"] += 1
                    print("       -> MATCH ACEPTADO (via conversacion)")
                    break
                else:
                    # Volvio al menu, mostrar opciones de nuevo
                    print(f"\n{SEPARATOR}")
                    display_match_result(result, meme_data, catalogo)
                    print(f"\n{SEPARATOR}")
                    continue

            elif choice in ('n', 'no', 'skip'):
                # Skip
                matches["skipped_buscar_clip"].append({
                    "shortcode": shortcode,
                    "clip_ideal_sugerido": result.get("clip_ideal", ""),
                    "ideas": result.get("ideas_alternativas", []),
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                save_matches(matches)
                stats["skipped"] += 1
                print("       -> SKIP (buscar clip mejor despues)")
                break

            elif choice in ('q', 'quit', 'salir'):
                print("\n   [SALIR] Progreso guardado.")
                _print_summary(stats, matches)
                return

            else:
                print("       [?] Usa: s/Enter, c, r, n, q")

        # Delay
        if i < len(batch) - 1:
            time.sleep(1)

    _print_summary(stats, matches)


def _print_summary(stats, matches):
    print(f"\n{SEPARATOR_EQ}")
    print("   RESUMEN")
    print(SEPARATOR_EQ)
    print(f"   Matched esta sesion: {stats['matched']}")
    print(f"   Skipped esta sesion: {stats['skipped']}")
    print(f"")
    print(f"   TOTALES:")
    print(f"     Total matched: {len(matches.get('matched', []))}")
    print(f"     Total pendientes (buscar clip): {len(matches.get('skipped_buscar_clip', []))}")
    print(f"   Guardado en: {MATCHES_FILE}")
    print(SEPARATOR_EQ)

    skipped = matches.get("skipped_buscar_clip", [])
    if skipped:
        print("\n   CLIPS QUE NECESITAS BUSCAR:")
        for item in skipped[-5:]:
            print(f"     - {item['shortcode']}: {item.get('clip_ideal_sugerido', '')[:80]}")


if __name__ == "__main__":
    main()
