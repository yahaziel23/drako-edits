#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descarga Individual de Instagram (CON LOGIN)

Descarga un post/reel/carousel especifico por URL.
Con login de cuenta burner. Mayor capacidad (300/dia vs 100).

Usa ig_tracker para control diario.

Output: tools_output/posts/_single/

Uso:
    python tools/instagram/single_login.py
    python tools/instagram/single_login.py --url "https://www.instagram.com/p/XXXXX/"
    python tools/instagram/single_login.py --status

Requisitos:
    pip install instaloader
"""

import sys
import io
import re
import time
from pathlib import Path

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent))
import ig_tracker

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent.parent
OUTPUT_DIR = SCRIPT_DIR / "tools_output" / "posts" / "_single"
SESSION_DIR = Path(__file__).parent / ".sessions"
METHOD = "login"
DELAY_BETWEEN = 3

# --- CREDENCIALES BURNER ---
BURNER_ACCOUNT = {
    "username": "",   # <-- tu burner
    "password": "",   # <-- password
}


# =============================================================================
# FUNCIONES
# =============================================================================

def get_instaloader_logged_in():
    """Crea instancia con login."""
    try:
        import instaloader
    except ImportError:
        print("   [X] pip install instaloader")
        sys.exit(1)

    if not BURNER_ACCOUNT["username"] or not BURNER_ACCOUNT["password"]:
        print("   [X] Configura BURNER_ACCOUNT en este archivo:")
        print(f"       {Path(__file__).resolve()}")
        sys.exit(1)

    L = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=False,
        download_comments=False,
        download_geotags=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="",
    )

    username = BURNER_ACCOUNT["username"]
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_file = SESSION_DIR / f"session-{username}"

    try:
        L.load_session_from_file(username, str(session_file))
        print(f"   [OK] Sesion: @{username}")
        return L, username
    except Exception:
        pass

    print(f"   Login: @{username}...")
    try:
        L.login(username, BURNER_ACCOUNT["password"])
        L.save_session_to_file(str(session_file))
        print(f"   [OK] Login exitoso.")
        return L, username
    except Exception as e:
        print(f"   [X] Error: {e}")
        sys.exit(1)


def extract_shortcode(url):
    """Extrae shortcode de URL."""
    patterns = [
        r'instagram\.com/p/([A-Za-z0-9_-]+)',
        r'instagram\.com/reel/([A-Za-z0-9_-]+)',
        r'instagram\.com/tv/([A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def download_single(url):
    """Descarga un post individual con login."""
    import instaloader

    shortcode = extract_shortcode(url)
    if not shortcode:
        print(f"   [X] URL no valida: {url}")
        return False

    account = BURNER_ACCOUNT["username"]

    if not ig_tracker.check_can_download(METHOD, account, 1):
        return False

    L, account = get_instaloader_logged_in()

    print(f"\n   Obteniendo: {shortcode}...")
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
    except Exception as e:
        print(f"   [X] Error: {e}")
        ig_tracker.log_request(METHOD, account, shortcode, "error")
        return False

    # Info
    type_map = {
        "GraphImage": "FOTO",
        "GraphVideo": "VIDEO/REEL",
        "GraphSidecar": "CAROUSEL",
    }
    media_type = post.typename
    type_label = type_map.get(media_type, "???")
    owner = post.owner_username

    print(f"   Tipo:   {type_label}")
    print(f"   De:     @{owner}")
    print(f"   Fecha:  {post.date_utc.strftime('%Y-%m-%d') if post.date_utc else '?'}")

    if media_type == "GraphSidecar":
        slides = list(post.get_sidecar_nodes())
        photos = sum(1 for s in slides if not s.is_video)
        videos = sum(1 for s in slides if s.is_video)
        print(f"   Slides: {len(slides)} ({photos} fotos, {videos} videos)")

    if post.caption:
        cap = post.caption[:80] + "..." if len(post.caption) > 80 else post.caption
        print(f"   Caption: {cap}")

    # Descargar
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n   Descargando...")

    try:
        L.download_post(post, target=str(OUTPUT_DIR))
        ig_tracker.log_request(METHOD, account, shortcode, type_label, owner)
        print(f"   [OK] Descargado en: {OUTPUT_DIR}")
        return True
    except Exception as e:
        print(f"   [X] Error: {e}")
        ig_tracker.log_request(METHOD, account, shortcode, "error", owner)
        return False


def interactive():
    """Flujo interactivo con login."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGA INDIVIDUAL (Instagram, CON LOGIN)")
    print("=" * 60)

    account = BURNER_ACCOUNT.get("username", "")
    remaining = ig_tracker.show_status(METHOD, account if account else None)

    if remaining <= 0:
        print("\n   Limite alcanzado.")
        return

    while True:
        print("\n--- URL ---")
        url = input("\n   URL (Enter=salir): ").strip()
        if not url:
            break

        success = download_single(url)

        remaining = ig_tracker.get_remaining(METHOD, account)
        print(f"\n   [LIMITE] Restantes: {remaining}")

        if remaining <= 0:
            print("   [X] Limite alcanzado.")
            break

        if success:
            time.sleep(DELAY_BETWEEN)

        cont = input("\n   Otro? (s/n): ").strip().lower()
        if cont != "s":
            break

    ig_tracker.show_status(METHOD, account if account else None)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Drako Edits - Descarga individual IG (con login)")
    parser.add_argument("--url", type=str, default=None)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    account = BURNER_ACCOUNT.get("username", "")

    if args.status:
        ig_tracker.show_status(METHOD, account if account else None)
    elif args.url:
        download_single(args.url)
    else:
        interactive()
