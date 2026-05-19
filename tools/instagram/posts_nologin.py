#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Descargar Fotos de Perfil (SIN LOGIN)

Descarga fotos de un perfil publico de Instagram sin necesidad de login.
Antes de descargar, escanea el perfil y te muestra:
  - Total de posts
  - Cuantos son imagenes
  - Cuantos son videos
  - Cuantos son carousels
Luego tu decides que descargar y cuantos.

Usa ig_tracker para controlar limites diarios con warm-up.

Output: tools_output/posts/{username}/

Uso:
    python tools/instagram/posts_nologin.py
    python tools/instagram/posts_nologin.py --username "cuenta" --max 20
    python tools/instagram/posts_nologin.py --status

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

# Agregar parent al path para importar ig_tracker
sys.path.insert(0, str(Path(__file__).parent))
import ig_tracker

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent.parent  # raiz del proyecto
OUTPUT_DIR = SCRIPT_DIR / "tools_output" / "posts"
METHOD = "nologin"

# Delays (conservadores sin login)
DELAY_BETWEEN_POSTS = 5
DELAY_SCAN = 2           # Delay al escanear tipo de posts
PAUSE_EVERY = 15
PAUSE_DURATION = 180     # 3 min


# =============================================================================
# FUNCIONES
# =============================================================================

def get_instaloader():
    """Crea instancia de instaloader sin login."""
    try:
        import instaloader
    except ImportError:
        print("   [X] Necesitas instalar instaloader:")
        print("       pip install instaloader")
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
    return L


def scan_profile(username):
    """
    Escanea un perfil y muestra estadisticas de tipos de post.
    Retorna (profile, stats) donde stats = {images, videos, carousels, total_scanned}
    
    NOTA: Cada post escaneado cuenta como request al API.
    """
    import instaloader

    L = get_instaloader()

    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as e:
        print(f"   [X] Error accediendo a @{username}: {e}")
        print("   [!] Verifica que el perfil sea publico y el username correcto.")
        return None, None

    print(f"\n   {'='*50}")
    print(f"   PERFIL: @{username}")
    print(f"   {'='*50}")
    print(f"   Posts totales:  {profile.mediacount}")
    print(f"   Seguidores:     {profile.followers}")
    print(f"   Siguiendo:      {profile.followees}")
    if profile.biography:
        bio_short = profile.biography[:60] + "..." if len(profile.biography) > 60 else profile.biography
        print(f"   Bio:            {bio_short}")

    if profile.is_private:
        print(f"\n   [X] Perfil PRIVADO. No se puede acceder sin login.")
        return None, None

    # Escanear tipos de posts
    # Limitar escaneo para no gastar demasiados requests
    remaining = ig_tracker.get_remaining(METHOD)
    max_scan = min(50, remaining // 2)  # Usar max 50% de lo que queda para escaneo

    if max_scan < 5:
        print(f"\n   [!] Muy pocos requests restantes ({remaining}) para escanear.")
        print(f"       No se puede hacer analisis de tipos.")
        return profile, None

    print(f"\n   Escaneando tipos de posts (max {max_scan} posts)...")
    print(f"   (Esto usa {max_scan} de tus {remaining} requests restantes)")

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

            # Registrar en tracker (escaneo tambien cuenta)
            ig_tracker.log_request(METHOD, shortcode=post.shortcode,
                                   media_type="scan", username=username)

            time.sleep(DELAY_SCAN)

    except Exception as e:
        print(f"   [!] Scan interrumpido: {e}")

    # Mostrar resultados
    total = stats["total_scanned"]
    print(f"\n   RESULTADO DEL SCAN ({total} posts analizados):")
    print(f"   {'─'*40}")
    print(f"   Imagenes:    {stats['images']:>4}  ({stats['images']/total*100:.0f}%)" if total else "")
    print(f"   Videos:      {stats['videos']:>4}  ({stats['videos']/total*100:.0f}%)" if total else "")
    print(f"   Carousels:   {stats['carousels']:>4}  ({stats['carousels']/total*100:.0f}%)" if total else "")
    print(f"   {'─'*40}")

    if profile.mediacount > total:
        ratio_img = stats['images'] / total if total else 0
        estimated_images = int(profile.mediacount * ratio_img)
        print(f"   (Estimado total de imagenes: ~{estimated_images} de {profile.mediacount} posts)")

    return profile, stats


def download_photos(username, max_download, profile=None):
    """
    Descarga fotos del perfil (solo GraphImage + fotos de carousels).
    """
    import instaloader

    L = get_instaloader()

    if profile is None:
        try:
            profile = instaloader.Profile.from_username(L.context, username)
        except Exception as e:
            print(f"   [X] Error: {e}")
            return

    # Verificar limite
    if not ig_tracker.check_can_download(METHOD, count=max_download):
        return

    remaining = ig_tracker.get_remaining(METHOD)
    actual_max = min(max_download, remaining)

    if actual_max < max_download:
        print(f"   [!] Ajustando a {actual_max} (limite de hoy)")

    # Crear carpeta
    user_dir = OUTPUT_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n   Descargando max {actual_max} fotos de @{username}...")
    print(f"   Delay: {DELAY_BETWEEN_POSTS}s | Pausa cada {PAUSE_EVERY}: {PAUSE_DURATION}s")
    print("")

    downloaded = 0
    checked = 0
    skipped_videos = 0

    try:
        for post in profile.get_posts():
            if downloaded >= actual_max:
                break

            checked += 1

            if post.typename == "GraphVideo":
                skipped_videos += 1
                print(f"   [{downloaded}/{actual_max}] skip video: {post.shortcode}")
                time.sleep(1)
                continue

            elif post.typename == "GraphImage":
                print(f"   [{downloaded+1}/{actual_max}] foto: {post.shortcode}", end="")
                try:
                    L.download_post(post, target=str(user_dir))
                    downloaded += 1
                    ig_tracker.log_request(METHOD, shortcode=post.shortcode,
                                           media_type="photo", username=username)
                    print(" [OK]")
                except Exception as e:
                    print(f" [X] {e}")
                    ig_tracker.log_request(METHOD, shortcode=post.shortcode,
                                           media_type="error", username=username)

            elif post.typename == "GraphSidecar":
                slides = list(post.get_sidecar_nodes())
                photo_slides = [s for s in slides if not s.is_video]
                if photo_slides:
                    print(f"   [{downloaded+1}/{actual_max}] carousel ({len(photo_slides)} fotos): {post.shortcode}", end="")
                    try:
                        L.download_post(post, target=str(user_dir))
                        downloaded += 1
                        ig_tracker.log_request(METHOD, shortcode=post.shortcode,
                                               media_type="carousel_photos", username=username)
                        print(" [OK]")
                    except Exception as e:
                        print(f" [X] {e}")
                        ig_tracker.log_request(METHOD, shortcode=post.shortcode,
                                               media_type="error", username=username)
                else:
                    skipped_videos += 1
                    print(f"   [{downloaded}/{actual_max}] skip carousel (solo videos): {post.shortcode}")
                    time.sleep(1)
                    continue

            # Rate limiting
            if downloaded < actual_max:
                if downloaded % PAUSE_EVERY == 0 and downloaded > 0:
                    print(f"\n   [pausa] {PAUSE_DURATION}s...")
                    time.sleep(PAUSE_DURATION)
                    print(f"   [pausa] Continuando...\n")
                else:
                    time.sleep(DELAY_BETWEEN_POSTS)

    except KeyboardInterrupt:
        print("\n\n   [!] Interrumpido.")
    except Exception as e:
        print(f"\n   [X] Error: {e}")
        print("   [!] Posible rate limit. Espera e intenta de nuevo.")

    # Resumen
    print(f"\n   {'='*50}")
    print(f"   RESUMEN")
    print(f"   {'='*50}")
    print(f"   Perfil:      @{username}")
    print(f"   Descargados: {downloaded}")
    print(f"   Skipped:     {skipped_videos} videos")
    print(f"   Carpeta:     {user_dir}")

    # Mostrar estado actualizado
    ig_tracker.show_status(METHOD)


# =============================================================================
# FLUJO INTERACTIVO
# =============================================================================

def interactive():
    """Flujo interactivo completo."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - DESCARGAR FOTOS (Instagram, sin login)")
    print("=" * 60)

    # Mostrar estado actual
    remaining = ig_tracker.show_status(METHOD)

    if remaining <= 0:
        print("\n   No puedes descargar hoy. Vuelve manana.")
        return

    # Mostrar descargas previas
    if OUTPUT_DIR.exists():
        users = [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name != "_single"]
        if users:
            print(f"\n   Perfiles previos:")
            for u in sorted(users):
                photos = list(u.glob("*.jpg")) + list(u.glob("*.png"))
                print(f"     - @{u.name} ({len(photos)} fotos)")

    # 1. Username
    print("\n--- PASO 1: Perfil ---")
    username = input("\n   Username (sin @): ").strip().lstrip("@")
    if not username:
        print("   [X] Saliendo.")
        return

    # 2. Escanear perfil (muestra estadisticas)
    print("\n--- PASO 2: Escaneando perfil ---")
    profile, stats = scan_profile(username)

    if profile is None:
        return

    # 3. Que descargar?
    print("\n--- PASO 3: Que descargar ---")
    print("   1. Solo imagenes (fotos individuales)")
    print("   2. Imagenes + fotos de carousels")
    # (videos no se descargan con este script)
    choice = input("\n   Opcion (1/2, default=2): ").strip()
    # Por ahora ambas opciones descargan fotos (incluyendo carousel fotos)
    # La diferencia seria filtrar carousels pero eso ya lo hace el código

    # 4. Cuantas?
    remaining = ig_tracker.get_remaining(METHOD)
    print(f"\n--- PASO 4: Cantidad ---")
    print(f"   Requests restantes hoy: {remaining}")

    if stats:
        suggested = min(stats["images"] + stats["carousels"], remaining, 30)
    else:
        suggested = min(remaining, 30)

    max_input = input(f"   Cuantos posts descargar? (default={suggested}): ").strip()
    max_download = int(max_input) if max_input.isdigit() else suggested

    # 5. Advertencia final
    print(f"\n--- PASO 5: Confirmacion ---")
    ig_tracker.check_can_download(METHOD, count=max_download)

    confirm = input(f"\n   Descargar {max_download} fotos de @{username}? (s/n): ").strip().lower()
    if confirm != "s":
        print("   Cancelado.")
        return

    # 6. Descargar
    print(f"\n--- PASO 6: Descargando ---")
    download_photos(username, max_download, profile)

    # Otro?
    otro = input("\n   Descargar de otro perfil? (s/n): ").strip().lower()
    if otro == "s":
        interactive()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Drako Edits - Descargar fotos IG (sin login)")
    parser.add_argument("--username", type=str, default=None)
    parser.add_argument("--max", type=int, default=30)
    parser.add_argument("--status", action="store_true", help="Solo ver estado")
    parser.add_argument("--history", action="store_true", help="Ver historial")
    args = parser.parse_args()

    if args.status:
        ig_tracker.show_status(METHOD)
    elif args.history:
        ig_tracker.get_history_summary()
    elif args.username:
        download_photos(args.username.lstrip("@"), args.max)
    else:
        interactive()
