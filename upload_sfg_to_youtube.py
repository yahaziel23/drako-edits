#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Upload a YouTube: Super Freaky Girl

Sube videos del formato Super Freaky Girl a YouTube como Shorts.
Extrae el nombre del archivo (sfg_DANIELA_roses.mp4 -> DANIELA) para
usar en el titulo.

Uso:
    python upload_sfg_to_youtube.py                        # Sube todos los nuevos
    python upload_sfg_to_youtube.py --num 5                # Sube solo 5 nuevos
    python upload_sfg_to_youtube.py --video sfg_DANIELA_roses.mp4  # Sube uno especifico
    python upload_sfg_to_youtube.py --force                # Ignora log, sube todos

Requisitos:
    - client_secrets.json en la raiz del repo
    - pip install google-api-python-client google-auth-oauthlib
"""

import os
import sys
import json
import random
import argparse
import time
from pathlib import Path
from datetime import datetime

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "assets" / "super_freaky_girl" / "output"
CLIENT_SECRETS_FILE = SCRIPT_DIR / "client_secrets.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"
UPLOAD_LOG_FILE = SCRIPT_DIR / "uploaded_sfg_log.json"

# Scopes necesarios para subir videos
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# --- TITULOS ROTATIVOS ---
# {name} se reemplaza con el nombre extraido del archivo
TITLES = [
    "Cuando se llama {name}...",
    "Cuando se llama {name}",
    "POV: se llama {name}",
    "Para ti {name}",
    "Se llama {name}?",
    "{name}...",
    "Este va para {name}",
    "Cuando se llama {name} pt.{n}",
    "Si se llama {name}...",
    "Para {name}",
    "{name} te lo dedico",
    "Cuando su nombre es {name}",
    "POV: ella se llama {name}",
    "Dedicado a {name}",
    "{name} pt.{n}",
]

# --- DESCRIPCION ---
# {name} se reemplaza con el nombre
DESCRIPTION = """Cuando se llama {name}...

Comenta un nombre y te lo hago!

#shorts #superfreakygirl #nickiminaj #nombre #edit #viral #fyp #parati #love #dedicatoria #freaky #trend"""

# --- CONFIG DE UPLOAD ---
CATEGORY_ID = "22"  # People & Blogs
PRIVACY_STATUS = "public"
WAIT_BETWEEN_UPLOADS = 30  # segundos entre cada upload


# =============================================================================
# UTILIDADES
# =============================================================================

def extract_name_from_filename(filename):
    """
    Extrae el nombre del archivo generado.
    Formato esperado: sfg_NOMBRE_theme.mp4
    Ejemplo: sfg_DANIELA_roses.mp4 -> DANIELA
    """
    stem = Path(filename).stem  # sfg_DANIELA_roses
    parts = stem.split("_")
    
    if len(parts) >= 3 and parts[0] == "sfg":
        # Todo entre sfg_ y _theme (el ultimo segmento es el theme)
        name_parts = parts[1:-1]
        return "_".join(name_parts)
    elif len(parts) >= 2 and parts[0] == "sfg":
        return parts[1]
    else:
        # Fallback: usar el stem completo
        return stem


def get_title(name, video_num):
    """Genera un titulo random con el nombre insertado."""
    title = random.choice(TITLES)
    title = title.replace("{name}", name.capitalize())
    title = title.replace("{n}", str(video_num))
    return title


def get_description(name):
    """Genera la descripcion con el nombre insertado."""
    return DESCRIPTION.replace("{name}", name.capitalize())


# =============================================================================
# UPLOAD LOG
# =============================================================================

def load_upload_log():
    """Carga el log de videos ya subidos."""
    if UPLOAD_LOG_FILE.exists():
        return json.loads(UPLOAD_LOG_FILE.read_text(encoding="utf-8"))
    return []


def save_upload_log(log):
    """Guarda el log de videos subidos."""
    UPLOAD_LOG_FILE.write_text(
        json.dumps(log, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def get_uploaded_filenames(log):
    """Retorna set de nombres de archivos ya subidos."""
    return {entry["file"] for entry in log}


# =============================================================================
# AUTENTICACION
# =============================================================================

def get_authenticated_service():
    """
    Autentica con YouTube API usando OAuth2.
    Primera vez: abre navegador. Despues usa token guardado.
    """
    credentials = None

    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("   Refrescando token...")
            credentials.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                print(f"\n   [X] ERROR: No se encontro {CLIENT_SECRETS_FILE}")
                print(f"   Descarga client_secrets.json de Google Cloud Console")
                print(f"   y colocalo en: {SCRIPT_DIR}")
                sys.exit(1)

            print("   Abriendo navegador para autorizar...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=8080)

        TOKEN_FILE.write_text(credentials.to_json())
        print("   [OK] Token guardado")

    return build("youtube", "v3", credentials=credentials)


# =============================================================================
# UPLOAD
# =============================================================================

def upload_video(youtube, video_path, video_num):
    """Sube un video a YouTube como Short."""
    name = extract_name_from_filename(video_path.name)
    title = get_title(name, video_num)
    description = get_description(name)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": ["shorts", "superfreakygirl", "nickiminaj", "nombre",
                     "edit", "viral", "fyp", "love", "dedicatoria",
                     "freaky", "trend", name.lower()],
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024
    )

    print(f"   Subiendo: {video_path.name}")
    print(f"   Nombre detectado: {name}")
    print(f"   Titulo: {title}")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"   Progreso: {progress}%", end="\r")

    video_id = response["id"]
    print(f"   [OK] Subido: https://youtube.com/shorts/{video_id}")
    return video_id, title, name


# =============================================================================
# MAIN
# =============================================================================

def upload_bulk(num_videos=None, specific_video=None, force=False):
    """Sube videos en bulk a YouTube."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - YOUTUBE UPLOADER (Super Freaky Girl)")
    print("=" * 60)

    # Cargar log
    upload_log = load_upload_log()
    already_uploaded = get_uploaded_filenames(upload_log)

    # Obtener lista de videos
    if specific_video:
        video_path = OUTPUT_DIR / specific_video
        if not video_path.exists():
            print(f"\n   [X] ERROR: Video no encontrado: {video_path}")
            sys.exit(1)
        videos = [video_path]
    else:
        all_videos = sorted(OUTPUT_DIR.glob("*.mp4"))

        if force:
            videos = all_videos
        else:
            videos = [v for v in all_videos if v.name not in already_uploaded]

        if num_videos:
            videos = videos[:num_videos]

    if not videos:
        if already_uploaded and not force:
            print(f"\n   [OK] Todos los videos ya fueron subidos ({len(already_uploaded)} en log)")
            print(f"   Usa --force para re-subir, o genera nuevos videos.")
        else:
            print(f"\n   [X] No hay videos en {OUTPUT_DIR}")
        return []

    print(f"\n   Videos nuevos a subir: {len(videos)}")
    if already_uploaded and not force:
        print(f"   Videos saltados (ya subidos): {len(already_uploaded)}")
    print(f"   Privacidad: {PRIVACY_STATUS}")
    print(f"   Espera entre uploads: {WAIT_BETWEEN_UPLOADS}s")

    # Autenticar
    print(f"\n   [AUTH] Conectando a YouTube...")
    youtube = get_authenticated_service()
    print(f"   [OK] Conectado\n")

    # Subir videos
    results = []
    total_count = len(upload_log)  # Para el {n} en titulos

    for i, video_path in enumerate(videos, 1):
        print(f"\n--- [{i}/{len(videos)}] ---")
        total_count += 1

        try:
            video_id, title, name = upload_video(youtube, video_path, total_count)

            # Registrar en log
            entry = {
                "file": video_path.name,
                "video_id": video_id,
                "title": title,
                "name": name,
                "url": f"https://youtube.com/shorts/{video_id}",
                "uploaded_at": datetime.now().isoformat(),
            }
            upload_log.append(entry)
            save_upload_log(upload_log)
            results.append(entry)

            # Esperar entre uploads (excepto el ultimo)
            if i < len(videos):
                print(f"   Esperando {WAIT_BETWEEN_UPLOADS}s...")
                time.sleep(WAIT_BETWEEN_UPLOADS)

        except Exception as e:
            print(f"   [X] Error subiendo {video_path.name}: {e}")
            continue

    # Resumen
    print(f"\n{'='*60}")
    print(f"   UPLOAD COMPLETO: {len(results)}/{len(videos)} videos subidos")
    print(f"   Log guardado en: {UPLOAD_LOG_FILE}")
    print(f"{'='*60}")

    if results:
        print(f"\n   Nombres subidos:")
        for r in results:
            print(f"   - {r['name']} -> {r['url']}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Drako Edits - YouTube Uploader (Super Freaky Girl)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python upload_sfg_to_youtube.py                        # Sube todos los nuevos
  python upload_sfg_to_youtube.py --num 3                # Sube solo 3
  python upload_sfg_to_youtube.py --video sfg_DANIELA_roses.mp4
  python upload_sfg_to_youtube.py --force                # Re-sube todos
        """
    )

    parser.add_argument("--num", type=int, default=None,
                        help="Numero maximo de videos a subir")
    parser.add_argument("--video", type=str, default=None,
                        help="Nombre de un video especifico a subir")
    parser.add_argument("--force", action="store_true",
                        help="Ignorar log y subir todos los videos")

    args = parser.parse_args()

    # Verificar que existe la carpeta de output
    if not OUTPUT_DIR.exists():
        print(f"\n[X] Carpeta de output no encontrada: {OUTPUT_DIR}")
        print(f"   Genera videos primero con generate_super_freaky_girl.py")
        sys.exit(1)

    upload_bulk(
        num_videos=args.num,
        specific_video=args.video,
        force=args.force
    )

    print("\n>>> Done!")


if __name__ == "__main__":
    main()
