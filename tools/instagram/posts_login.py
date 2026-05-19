#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descargar Fotos de Perfil (CON LOGIN)

Igual que posts_nologin.py pero con login de cuenta burner.
Mayor capacidad: hasta 300 requests/dia (vs 100 sin login).
Puede acceder a perfiles privados que la burner siga.

Configurar credenciales en BURNER_ACCOUNT abajo.

Output: tools_output/posts/{username}/

Uso:
    python tools/instagram/posts_login.py
    python tools/instagram/posts_login.py --username "cuenta" --max 50
    python tools/instagram/posts_login.py --status

Requisitos:
    pip install instaloader
"""

import sys
import io
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
OUTPUT_DIR = SCRIPT_DIR / "tools_output" / "posts"
SESSION_DIR = Path(__file__).parent / ".sessions"
METHOD = "login"

# --- CREDENCIALES BURNER ---
# Configurar con tu cuenta secundaria
BURNER_ACCOUNT = {
    "username": "",   # <-- tu burner
    "password": "",   # <-- password
}

# Delays (menos conservadores con login)
DELAY_BETWEEN_POSTS = 3
DELAY_SCAN = 1.5
PAUSE_EVERY = 30
PAUSE_DURATION = 120  # 2 min


# =============================================================================
# FUNCIONES
# =============================================================================

def get_instaloader_logged_in():
    """Crea instancia de instaloader con login y sesion guardada."""
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
        download_videos=False,
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

    # Intentar sesion guardada
    try:
        L.load_session_from_file(username, str(session_file))
        print(f"   [OK] Sesion reutilizada: @{username}")
        return L, username
    except Exception:
        pass

    # Login nuevo
    print(f"   Haciendo login como @{username}...")
    try:
        L.login(username, BURNER_ACCOUNT["password"])
        L.save_session_to_file(str(session_file))
        print(f"   [OK] Login exitoso. Sesion guardada.")
        return L, username
    except Exception as e:
        print(f"   [X] Error login: {e}")
        print("   [!] Verifica credenciales / desactiva 2FA / espera si bloqueado.")
        sys.exit(1)


def scan_profile(username):
    """Escanea perfil y muestra stats."""
    import instaloader

    L, account = get_instaloader_logged_in()

    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as e:
        print(f"   [X] Error accediendo a @{username}: {e}")
        return None, None

    print(f"\n   {'='*50}")
    print(f"   PERFIL: @{username}")
    print(f"   {'='*50}")
    print(f"   Posts totales:  {profile.mediacount}")
    print(f"   Seguidores:     {profile.followers}")
    print(f"   Siguiendo:      {profile.followees}")
    print(f"   Privado:        {'Si' if profile.is_private else 'No'}")
    if profile.biography:
        bio_short = profile.biography[:60] + "..." if len(profile.biography) > 60 else profile.biography
        print(f"   Bio:            {bio_short}")

    # Escanear tipos
    remaining = ig_tracker.get_remaining(METHOD, account)
    max_scan = min(80, remaining // 2)

    if max_scan < 5:
        print(f"\n   [!] Pocos requests ({remaining}). No scan.")
        return profile, None

    print(f"\n   Escaneando tipos (max {max_scan})...")

    stats = {"images": 0, "videos": 0, "carousels": 0, "total_scanned": 0}

    try:
        for i, post in enumerate(profile.get_posts()):
            if i >= max_scan:
                break
            if post.typename == "GraphImage":
                stats["images"] += 1
            elif post.typename == "GraphVideo":
                stats["videos"] += 1
            elif post.typename == "GraphSidecar":
                stats["carousels"] += 1
            stats["total_scanned"] += 1
            ig_tracker.log_request(METHOD, account, post.shortcode, "scan", username)
            time.sleep(DELAY_SCAN)
    except Exception as e:
        print(f"   [!] Scan cortado: {e}")

    total = stats["total_scanned"]
    if total:
        print(f"\n   SCAN ({total} posts):")
        print(f"   {'─'*40}")
        print(f"   Imagenes:    {stats['images']:>4}  ({stats['images']/total*100:.0f}%)")
        print(f"   Videos:      {stats['videos']:>4}  ({stats['videos']/total*100:.0f}%)")
        print(f"   Carousels:   {stats['carousels']:>4}  ({stats['carousels']/total*100:.0f}%)")
        print(f"   {'─'*40}")

    return profile, stats


def download_photos(username, max_download, profile=None):
    """Descarga fotos con login."""
    import instaloader

    L, account = get_instaloader_logged_in()

    if profile is None:
        try:
            profile = instaloader.Profile.from_username(L.context, username)
        except Exception as e:
            print(f"   [X] Error: {e}")
            return

    if not ig_tracker.check_can_download(METHOD, account, max_download):
        return

    remaining = ig_tracker.get_remaining(METHOD, account)
    actual_max = min(max_download, remaining)

    user_dir = OUTPUT_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n   Descargando max {actual_max} fotos de @{username} (con login)...")
    print("")

    downloaded = 0
    skipped = 0

    try:
        for post in profile.get_posts():
            if downloaded >= actual_max:
                break

            if post.typename == "GraphVideo":
                skipped += 1
                time.sleep(1)
                continue

            elif post.typename in ("GraphImage", "GraphSidecar"):
                if post.typename == "GraphSidecar":
                    slides = list(post.get_sidecar_nodes())
                    if not any(not s.is_video for s in slides):
                        skipped += 1
                        continue

                print(f"   [{downloaded+1}/{actual_max}] {post.typename}: {post.shortcode}", end="")
                try:
                    L.download_post(post, target=str(user_dir))
                    downloaded += 1
                    ig_tracker.log_request(METHOD, account, post.shortcode,
                                           post.typename, username)
                    print(" [OK]")
                except Exception as e:
                    print(f" [X] {e}")

            if downloaded < actual_max:
                if downloaded % PAUSE_EVERY == 0 and downloaded > 0:
                    print(f"\n   [pausa] {PAUSE_DURATION}s...")
                    time.sleep(PAUSE_DURATION)
                else:
                    time.sleep(DELAY_BETWEEN_POSTS)

    except KeyboardInterrupt:
        print("\n   [!] Interrumpido.")
    except Exception as e:
        print(f"\n   [X] {e}")

    print(f"\n   RESUMEN: {downloaded} descargados, {skipped} videos saltados")
    print(f"   Carpeta: {user_dir}")
    ig_tracker.show_status(METHOD, account)


def interactive():
    """Flujo interactivo con login."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGAR FOTOS (Instagram, CON LOGIN)")
    print("=" * 60)

    account = BURNER_ACCOUNT.get("username", "")
    remaining = ig_tracker.show_status(METHOD, account if account else None)

    if remaining <= 0:
        print("\n   Limite alcanzado. Vuelve manana.")
        return

    # Username
    print("\n--- Perfil ---")
    username = input("\n   Username (sin @): ").strip().lstrip("@")
    if not username:
        return

    # Scan
    print("\n--- Escaneando ---")
    profile, stats = scan_profile(username)
    if profile is None:
        return

    # Cantidad
    remaining = ig_tracker.get_remaining(METHOD, account)
    print(f"\n--- Cantidad ---")
    print(f"   Restantes hoy: {remaining}")
    suggested = min(50, remaining)
    max_input = input(f"   Cuantos descargar? (default={suggested}): ").strip()
    max_download = int(max_input) if max_input.isdigit() else suggested

    # Confirmar
    confirm = input(f"\n   Descargar {max_download} fotos de @{username}? (s/n): ").strip().lower()
    if confirm != "s":
        return

    download_photos(username, max_download, profile)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Drako Edits - Descargar fotos IG (con login)")
    parser.add_argument("--username", type=str, default=None)
    parser.add_argument("--max", type=int, default=50)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        account = BURNER_ACCOUNT.get("username", "")
        ig_tracker.show_status(METHOD, account if account else None)
    elif args.username:
        download_photos(args.username.lstrip("@"), args.max)
    else:
        interactive()
