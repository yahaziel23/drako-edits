#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Auto Meme Reaction (Automatizado)

Pipeline automatico: Login IG -> Descarga 1 meme -> Clasificacion IA -> Video
Le das play y se genera un video solo sin intervencion manual.

Por ahora solo: Login + Descarga 1 foto (sin repetir).
Lo demas se activa cuando confirmemos que funciona.

Requiere .env en la raiz del proyecto con:
    OPENAI_API_KEY=sk-...
    IG_USERNAME=tu_burner
    IG_PASSWORD=tu_password

Uso:
    python automatizaciones/auto_meme_reaction.py
"""

import os
import sys
import io
import json
from pathlib import Path
from datetime import date

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from instagrapi import Client as IGClient


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent  # automatizaciones/ -> drako-edits/

# Cargar .env desde la raiz del proyecto
ENV_PATH = SCRIPT_DIR / ".env"
if load_dotenv and ENV_PATH.exists():
    load_dotenv(ENV_PATH)
elif load_dotenv:
    load_dotenv()

IG_USERNAME = os.environ.get("IG_USERNAME", "")
IG_PASSWORD = os.environ.get("IG_PASSWORD", "")

if not IG_USERNAME or not IG_PASSWORD:
    print("[ERROR] Falta IG_USERNAME / IG_PASSWORD en .env")
    print(f"   Buscado en: {ENV_PATH}")
    sys.exit(1)

# Directorios
IMAGES_DIR = SCRIPT_DIR / "tools_output" / "posts"
SESSION_FILE = Path(__file__).parent / "ig_session.json"
HISTORY_FILE = Path(__file__).parent / "downloaded_posts.json"

# Perfil objetivo
TARGET_PROFILE = "elmello2023"


# =============================================================================
# SESION (login una sola vez, reutiliza despues)
# =============================================================================

def get_ig_client():
    """Crea cliente de instagrapi con login. Reutiliza sesion si existe."""
    cl = IGClient()

    # Intentar reutilizar sesion guardada
    if SESSION_FILE.exists():
        try:
            cl.load_settings(str(SESSION_FILE))
            cl.login(IG_USERNAME, IG_PASSWORD)
            print(f"[OK] Sesion reutilizada: @{IG_USERNAME}")
            return cl
        except Exception:
            print(f"   [!] Sesion expirada, haciendo login nuevo...")

    # Login nuevo
    print(f"[IG] Iniciando sesion como @{IG_USERNAME}...")
    try:
        cl.login(IG_USERNAME, IG_PASSWORD)
        cl.dump_settings(str(SESSION_FILE))
        print(f"[OK] Login exitoso. Sesion guardada en: {SESSION_FILE.name}")
    except Exception as e:
        print(f"[X] Error login: {e}")
        print("   Verifica credenciales / confirma challenge desde la app de IG")
        sys.exit(1)

    return cl


# =============================================================================
# HISTORIAL (no repetir posts)
# =============================================================================

def load_history():
    """Carga historial de shortcodes ya descargados."""
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {"downloaded": []}
    return {"downloaded": []}


def save_history(history):
    """Guarda historial."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# =============================================================================
# DESCARGAR 1 FOTO
# =============================================================================

def fetch_one_photo(cl, target_username):
    """
    Busca UN post tipo foto (media_type=1) que no se haya descargado antes.
    Retorna (image_path, shortcode) o (None, None).
    """
    print(f"\n[IG] Buscando foto nueva en @{target_username}...")

    # Historial
    history = load_history()
    already = set(history.get("downloaded", []))
    print(f"   Ya descargados: {len(already)}")

    # Obtener perfil
    try:
        user_id = cl.user_id_from_username(target_username)
        user_info = cl.user_info(user_id)
        print(f"   Perfil: @{target_username} ({user_info.media_count} posts)")
    except Exception as e:
        print(f"   [X] Error accediendo a @{target_username}: {e}")
        return None, None

    # Obtener posts recientes
    print(f"   Obteniendo posts...")
    try:
        medias = cl.user_medias(user_id, amount=50)
    except Exception as e:
        print(f"   [X] Error obteniendo posts: {e}")
        return None, None

    print(f"   Posts obtenidos: {len(medias)}")

    # Buscar primera foto nueva
    for i, media in enumerate(medias, 1):
        if media.code in already:
            continue
        # Solo fotos (1=Photo, 2=Video, 8=Carousel)
        if media.media_type != 1:
            continue

        print(f"   [OK] Foto nueva encontrada: {media.code} (#{i} de {len(medias)})")

        # Descargar
        save_dir = IMAGES_DIR / target_username
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            image_path = Path(cl.photo_download(media.pk, folder=str(save_dir)))
            size_kb = image_path.stat().st_size / 1024
            print(f"   [OK] Descargado: {image_path.name} ({size_kb:.1f} KB)")
        except Exception as e:
            print(f"   [X] Error descargando: {e}")
            return None, None

        # Registrar en historial
        history["downloaded"].append(media.code)
        history["last_download"] = {
            "shortcode": media.code,
            "username": target_username,
            "date": str(date.today()),
            "file": image_path.name
        }
        save_history(history)
        print(f"   [OK] Registrado en historial")

        return image_path, media.code

    print(f"   [!] No hay fotos nuevas en @{target_username}")
    return None, None


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - AUTO MEME REACTION")
    print("=" * 60)

    # Login
    cl = get_ig_client()

    # Descargar 1 foto
    meme_path, shortcode = fetch_one_photo(cl, TARGET_PROFILE)

    # Resultado
    print(f"\n{'='*60}")
    if meme_path:
        print(f"   [OK] LISTO")
        print(f"   Meme:      {meme_path.name}")
        print(f"   Shortcode: {shortcode}")
        print(f"   Path:      {meme_path}")
    else:
        print(f"   [!] No se descargo nada")
    print(f"{'='*60}")

    # TODO (activar despues):
    # - Paso 2: classify_meme(meme_path) con OpenAI Vision
    # - Paso 3: pick_reaction_clip(classification)
    # - Paso 4: generate_caption(classification)
    # - Paso 5: generar video con meme_reaction logic


if __name__ == "__main__":
    main()
