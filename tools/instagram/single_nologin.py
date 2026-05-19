#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descarga Individual de Instagram (SIN LOGIN)

Descarga un post/reel/carousel especifico por URL.
Sin login, solo contenido publico.

Antes de cada descarga te muestra:
  - Cuantos requests llevas hoy
  - Cuantos te quedan
  - Advertencia si estas cerca del limite

Usa ig_tracker para llevar control diario con warm-up.

Output: tools_output/posts/_single/

Uso:
    python tools/instagram/single_nologin.py
    python tools/instagram/single_nologin.py --url "https://www.instagram.com/p/XXXXX/"
    python tools/instagram/single_nologin.py --status

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
METHOD = "nologin"
DELAY_BETWEEN = 5


# =============================================================================
# FUNCIONES
# =============================================================================

def extract_shortcode(url):
    """Extrae shortcode de URL de Instagram."""
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
    """Descarga un post individual por URL."""
    try:
        import instaloader
    except ImportError:
        print("   [X] pip install instaloader")
        sys.exit(1)

    # Extraer shortcode
    shortcode = extract_shortcode(url)
    if not shortcode:
        print(f"   [X] URL no valida: {url}")
        print("   Formatos: instagram.com/p/XXX/ o instagram.com/reel/XXX/")
        return False

    # Verificar limite
    if not ig_tracker.check_can_download(METHOD, count=1):
        return False

    # Crear instancia
    L = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=False,
        download_comments=False,
        download_geotags=False,
        save_metadata=True,
        compress_json=False,
        post_metadata_txt_pattern="",
    )

    # Obtener post
    print(f"\n   Obteniendo: {shortcode}...")
    try:
        post = instaloader.Post.from_shortcode(L.context, shortcode)
    except Exception as e:
        print(f"   [X] Error: {e}")
        print("   [!] Verifica que el post sea publico.")
        ig_tracker.log_request(METHOD, shortcode=shortcode, media_type="error")
        return False

    # Info del post
    type_map = {
        "GraphImage": "FOTO",
        "GraphVideo": "VIDEO/REEL",
        "GraphSidecar": "CAROUSEL",
    }
    media_type = post.typename
    type_label = type_map.get(media_type, "???")
    owner = post.owner_username
    post_date = post.date_utc.strftime("%Y-%m-%d") if post.date_utc else "?"

    print(f"   Tipo:   {type_label}")
    print(f"   De:     @{owner}")
    print(f"   Fecha:  {post_date}")

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
        ig_tracker.log_request(METHOD, shortcode=shortcode,
                               media_type=type_label, username=owner)
        print(f"   [OK] Descargado en: {OUTPUT_DIR}")
        return True
    except Exception as e:
        print(f"   [X] Error: {e}")
        ig_tracker.log_request(METHOD, shortcode=shortcode, media_type="error")
        return False


def interactive():
    """Flujo interactivo."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGA INDIVIDUAL (Instagram, sin login)")
    print("=" * 60)

    # Estado
    remaining = ig_tracker.show_status(METHOD)

    if remaining <= 0:
        print("\n   Limite alcanzado. Vuelve manana.")
        return

    # Loop
    while True:
        print("\n--- URL del post/reel/carousel ---")
        print("   (Enter vacio para salir)")
        url = input("\n   URL: ").strip()

        if not url:
            break

        success = download_single(url)

        # Mostrar estado actualizado
        remaining = ig_tracker.get_remaining(METHOD)
        print(f"\n   [LIMITE] Restantes hoy: {remaining}")

        if remaining <= 0:
            print("   [X] Limite alcanzado.")
            break

        if success:
            time.sleep(DELAY_BETWEEN)

        cont = input("\n   Descargar otro? (s/n): ").strip().lower()
        if cont != "s":
            break

    ig_tracker.show_status(METHOD)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Drako Edits - Descarga individual IG (sin login)")
    parser.add_argument("--url", type=str, default=None)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args()

    if args.status:
        ig_tracker.show_status(METHOD)
    elif args.history:
        ig_tracker.get_history_summary()
    elif args.url:
        download_single(args.url)
    else:
        interactive()
