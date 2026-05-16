#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Upload automatico a YouTube Shorts

Sube videos generados a YouTube como Shorts con titulos rotativos
y descripcion con hashtags.

Uso:
    python upload_to_youtube.py                     # Sube todos los videos en output/
    python upload_to_youtube.py --num 5             # Sube solo 5 videos
    python upload_to_youtube.py --video video_001.mp4  # Sube un video especifico

Requisitos:
    1. Crear proyecto en Google Cloud Console
    2. Habilitar YouTube Data API v3
    3. Crear credenciales OAuth2 (Desktop App)
    4. Descargar client_secrets.json y ponerlo en la raiz del repo
    5. pip install google-api-python-client google-auth-oauthlib

Primera vez: Se abre el navegador para autorizar. Despues usa token guardado.
"""

import os
import sys
import random
import argparse
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output" / "si_no_te_quieres_banar"
CLIENT_SECRETS_FILE = SCRIPT_DIR / "client_secrets.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"

# Scopes necesarios para subir videos
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# --- TITULOS ROTATIVOS ---
# Se asignan random a cada video. Agrega mas si quieres variedad.
TITLES = [
    "Si no te quieres bañar... 💀",
    "A NO 😭😭",
    "De color vas a cambiar 🗿",
    "Tatiana lo predijo 💀",
    "No te bañas? 🤨📸",
    "POV: no te quieres bañar",
    "Si no te quieres bañar pt.{n}",
    "El que no se baña: 🗿",
    "Tatiana tenia razon 💀",
    "A NO JAJAJA 😭",
    "Bañate bro 🗿",
    "Si no te quieres bañar... 😭",
    "De color vas a cambiar 💀",
    "No te bañas?? 🗿📸",
    "Tatiana awakened 💀",
    "A ver bañate 🤨",
    "Si no te quieres bañar hmm 🗿",
    "No se baña el compa 💀",
    "De que color? 🗿",
    "A NO pt.{n}",
]

# --- DESCRIPCION (misma para todos) ---
DESCRIPTION = """Si no te quieres bañar 🗿

#shorts #memes #shitpost #humor #edit #viral #fyp #parati #sinotequieresbanar #tatiana #meme #edits #funny #humor"""

# --- CONFIG DE UPLOAD ---
CATEGORY_ID = "23"  # Comedy
PRIVACY_STATUS = "public"  # public, unlisted, private
WAIT_BETWEEN_UPLOADS = 30  # segundos entre cada upload (evita rate limit)


# =============================================================================
# AUTENTICACION
# =============================================================================

def get_authenticated_service():
    """
    Autentica con YouTube API usando OAuth2.
    Primera vez: abre navegador. Despues usa token guardado.
    """
    credentials = None

    # Intentar cargar token existente
    if TOKEN_FILE.exists():
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # Si no hay token valido, hacer flujo OAuth
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            print("   Refrescando token...")
            credentials.refresh(Request())
        else:
            if not CLIENT_SECRETS_FILE.exists():
                print(f"\n   ❌ ERROR: No se encontro {CLIENT_SECRETS_FILE}")
                print(f"   Descarga client_secrets.json de Google Cloud Console")
                print(f"   y colocalo en: {SCRIPT_DIR}")
                sys.exit(1)

            print("   Abriendo navegador para autorizar...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRETS_FILE), SCOPES
            )
            credentials = flow.run_local_server(port=8080)

        # Guardar token para proxima vez
        TOKEN_FILE.write_text(credentials.to_json())
        print("   ✅ Token guardado")

    return build("youtube", "v3", credentials=credentials)


# =============================================================================
# UPLOAD
# =============================================================================

def get_title(video_num):
    """Genera un titulo random, reemplazando {n} con el numero."""
    title = random.choice(TITLES)
    return title.replace("{n}", str(video_num))


def upload_video(youtube, video_path, video_num):
    """Sube un video a YouTube como Short."""
    title = get_title(video_num)

    body = {
        "snippet": {
            "title": title,
            "description": DESCRIPTION,
            "tags": ["shorts", "memes", "shitpost", "humor", "edit",
                     "viral", "fyp", "tatiana", "sinotequieresbanar"],
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
        chunksize=1024 * 1024  # 1MB chunks
    )

    print(f"   Subiendo: {video_path.name}")
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
    print(f"   ✅ Subido: https://youtube.com/shorts/{video_id}")
    return video_id


# =============================================================================
# MAIN
# =============================================================================

def upload_bulk(num_videos=None, specific_video=None):
    """Sube videos en bulk a YouTube."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - YOUTUBE UPLOADER")
    print("=" * 60)

    # Obtener lista de videos
    if specific_video:
        video_path = OUTPUT_DIR / specific_video
        if not video_path.exists():
            print(f"\n   ❌ ERROR: Video no encontrado: {video_path}")
            sys.exit(1)
        videos = [video_path]
    else:
        videos = sorted(OUTPUT_DIR.glob("*.mp4"))
        if num_videos:
            videos = videos[:num_videos]

    if not videos:
        print(f"\n   ❌ ERROR: No hay videos en {OUTPUT_DIR}")
        sys.exit(1)

    print(f"\n   Videos a subir: {len(videos)}")
    print(f"   Privacidad: {PRIVACY_STATUS}")
    print(f"   Espera entre uploads: {WAIT_BETWEEN_UPLOADS}s")

    # Autenticar
    print(f"\n   [AUTH] Conectando a YouTube...")
    youtube = get_authenticated_service()
    print(f"   ✅ Conectado\n")

    # Subir videos
    uploaded = []
    for i, video_path in enumerate(videos, 1):
        print(f"\n   [{i}/{len(videos)}]")
        try:
            video_id = upload_video(youtube, video_path, i)
            uploaded.append({"file": video_path.name, "id": video_id})

            # Esperar entre uploads (evitar rate limit)
            if i < len(videos):
                print(f"   Esperando {WAIT_BETWEEN_UPLOADS}s...")
                time.sleep(WAIT_BETWEEN_UPLOADS)

        except Exception as e:
            print(f"   ❌ Error: {e}")
            continue

    # Resumen
    print(f"\n\n{'='*60}")
    print(f"   RESUMEN DE UPLOADS")
    print(f"{'='*60}")
    print(f"   Subidos: {len(uploaded)}/{len(videos)}")
    for v in uploaded:
        print(f"     ✅ {v['file']} -> https://youtube.com/shorts/{v['id']}")
    print(f"{'='*60}\n")

    return uploaded


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - YouTube Uploader")
    parser.add_argument("--num", type=int, default=None,
                        help="Numero de videos a subir (default: todos)")
    parser.add_argument("--video", type=str, default=None,
                        help="Nombre de un video especifico a subir")
    args = parser.parse_args()

    upload_bulk(num_videos=args.num, specific_video=args.video)
