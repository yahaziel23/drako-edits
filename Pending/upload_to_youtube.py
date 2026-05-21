#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Upload automatico a YouTube Shorts

Sube videos generados a YouTube como Shorts con titulos rotativos
y descripcion con hashtags. Trackea videos ya subidos para no repetir.

Uso:
    python upload_to_youtube.py                     # Sube todos los videos NUEVOS en output/
    python upload_to_youtube.py --num 5             # Sube solo 5 videos nuevos
    python upload_to_youtube.py --video video_001.mp4  # Sube un video especifico (aunque ya se haya subido)
    python upload_to_youtube.py --force             # Sube todos ignorando el log

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
OUTPUT_DIR = SCRIPT_DIR / "output" / "si_no_te_quieres_banar"
CLIENT_SECRETS_FILE = SCRIPT_DIR / "client_secrets.json"
TOKEN_FILE = SCRIPT_DIR / "token.json"
UPLOAD_LOG_FILE = SCRIPT_DIR / "uploaded_log.json"

# Scopes necesarios para subir videos
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# --- TITULOS ROTATIVOS ---
# Se asignan random a cada video. Agrega mas si quieres variedad.
TITLES = [
    "Si no te quieres ba\u00f1ar... \ud83d\udc80",
    "A NO \ud83d\ude2d\ud83d\ude2d",
    "De color vas a cambiar \ud83d\uddff",
    "Tatiana lo predijo \ud83d\udc80",
    "No te ba\u00f1as? \ud83e\udd28\ud83d\udcf8",
    "POV: no te quieres ba\u00f1ar",
    "Si no te quieres ba\u00f1ar pt.{n}",
    "El que no se ba\u00f1a: \ud83d\uddff",
    "Tatiana tenia razon \ud83d\udc80",
    "A NO JAJAJA \ud83d\ude2d",
    "Ba\u00f1ate bro \ud83d\uddff",
    "Si no te quieres ba\u00f1ar... \ud83d\ude2d",
    "De color vas a cambiar \ud83d\udc80",
    "No te ba\u00f1as?? \ud83d\uddff\ud83d\udcf8",
    "Tatiana awakened \ud83d\udc80",
    "A ver ba\u00f1ate \ud83e\udd28",
    "Si no te quieres ba\u00f1ar hmm \ud83d\uddff",
    "No se ba\u00f1a el compa \ud83d\udc80",
    "De que color? \ud83d\uddff",
    "A NO pt.{n}",
]

# --- DESCRIPCION (misma para todos) ---
DESCRIPTION = """Si no te quieres ba\u00f1ar \ud83d\uddff

#shorts #memes #shitpost #humor #edit #viral #fyp #parati #sinotequieresbanar #tatiana #meme #edits #funny #humor"""

# --- CONFIG DE UPLOAD ---
CATEGORY_ID = "23"  # Comedy
PRIVACY_STATUS = "public"  # public, unlisted, private
WAIT_BETWEEN_UPLOADS = 30  # segundos entre cada upload (evita rate limit)


# =============================================================================
# UPLOAD LOG - Trackea videos ya subidos
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
                print(f"\n   \u274c ERROR: No se encontro {CLIENT_SECRETS_FILE}")
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
        print("   \u2705 Token guardado")

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
    print(f"   \u2705 Subido: https://youtube.com/shorts/{video_id}")
    return video_id, title


# =============================================================================
# MAIN
# =============================================================================

def upload_bulk(num_videos=None, specific_video=None, force=False):
    """Sube videos en bulk a YouTube. Salta los que ya se subieron."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - YOUTUBE UPLOADER")
    print("=" * 60)

    # Cargar log de videos ya subidos
    upload_log = load_upload_log()
    already_uploaded = get_uploaded_filenames(upload_log)

    # Obtener lista de videos
    if specific_video:
        video_path = OUTPUT_DIR / specific_video
        if not video_path.exists():
            print(f"\n   \u274c ERROR: Video no encontrado: {video_path}")
            sys.exit(1)
        videos = [video_path]
    else:
        all_videos = sorted(OUTPUT_DIR.glob("*.mp4"))

        # Filtrar videos ya subidos (a menos que sea --force)
        if force:
            videos = all_videos
        else:
            videos = [v for v in all_videos if v.name not in already_uploaded]

        if num_videos:
            videos = videos[:num_videos]

    if not videos:
        if already_uploaded and not force:
            print(f"\n   \u2705 Todos los videos ya fueron subidos ({len(already_uploaded)} en log)")
            print(f"   Usa --force para re-subir, o genera nuevos videos.")
        else:
            print(f"\n   \u274c ERROR: No hay videos en {OUTPUT_DIR}")
        return []

    print(f"\n   Videos nuevos a subir: {len(videos)}")
    if already_uploaded and not force:
        print(f"   Videos saltados (ya subidos): {len(already_uploaded)}")
    print(f"   Privacidad: {PRIVACY_STATUS}")
    print(f"   Espera entre uploads: {WAIT_BETWEEN_UPLOADS}s")

    # Autenticar
    print(f"\n   [AUTH] Conectando a YouTube...")
    youtube = get_authenticated_service()
    print(f"   \u2705 Conectado\n")

    # Subir videos
    uploaded = []
    for i, video_path in enumerate(videos, 1):
        print(f"\n   [{i}/{len(videos)}]")
        try:
            video_id, title = upload_video(youtube, video_path, i)
            uploaded.append({"file": video_path.name, "id": video_id})

            # Registrar en log
            upload_log.append({
                "file": video_path.name,
                "youtube_id": video_id,
                "title": title,
                "uploaded_at": datetime.now().isoformat(),
            })
            save_upload_log(upload_log)

            # Esperar entre uploads (evitar rate limit)
            if i < len(videos):
                print(f"   Esperando {WAIT_BETWEEN_UPLOADS}s...")
                time.sleep(WAIT_BETWEEN_UPLOADS)

        except Exception as e:
            print(f"   \u274c Error: {e}")
            continue

    # Resumen
    print(f"\n\n{'='*60}")
    print(f"   RESUMEN DE UPLOADS")
    print(f"{'='*60}")
    print(f"   Subidos: {len(uploaded)}/{len(videos)}")
    print(f"   Total historico: {len(upload_log)} videos")
    for v in uploaded:
        print(f"     \u2705 {v['file']} -> https://youtube.com/shorts/{v['id']}")
    print(f"{'='*60}\n")

    return uploaded


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - YouTube Uploader")
    parser.add_argument("--num", type=int, default=None,
                        help="Numero de videos a subir (default: todos los nuevos)")
    parser.add_argument("--video", type=str, default=None,
                        help="Nombre de un video especifico a subir")
    parser.add_argument("--force", action="store_true",
                        help="Ignorar log y subir todos (incluso repetidos)")
    args = parser.parse_args()

    upload_bulk(num_videos=args.num, specific_video=args.video, force=args.force)
