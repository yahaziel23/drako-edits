#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Paso 1B: Scrape de Posts Nuevos (Multi-Perfil)

Ejecución regular: recorre TODOS los perfiles de config.json,
scrollea poco (2-3 scrolls) y solo registra posts NUEVOS.
Diseñado para escalar a 100+ perfiles.

Optimizaciones:
- Si un perfil no tiene nuevos en N ejecuciones seguidas, se salta
- Early exit si encuentra todos los shortcodes ya conocidos (no hay nuevos)
- Delay entre perfiles para evitar rate limit
- Resumen al final: X perfiles visitados, Y posts nuevos

Uso:
    python 1b_scrape_nuevos.py                   # Todos los perfiles
    python 1b_scrape_nuevos.py --max-perfiles 10  # Solo 10 perfiles
    python 1b_scrape_nuevos.py --dry-run           # No guarda en DB

Dependencias: selenium, webdriver-manager
"""

import sys
import time
import re
import random
import uuid
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# Setup path
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from utils.db import init_db, get_db, insert_meme, start_pipeline_run, finish_pipeline_run
from utils.config import load_config, get_section
from utils.logger import setup_logger, get_logger, track_item, log_summary
from utils.health import run_health_checks
from utils.rate_limiter import RateLimiter
from utils.telegram import send_notification


# =============================================================================
# SELENIUM HELPERS (compartidos con 1a)
# =============================================================================

def get_brave_version(brave_path):
    """Detecta versión major de Brave."""
    try:
        if sys.platform == "win32":
            ps_cmd = (
                'powershell -Command "'
                f"(Get-Item '{brave_path}').VersionInfo.FileVersion"
                '"'
            )
            result = subprocess.run(
                ps_cmd, capture_output=True, text=True, shell=True, timeout=15
            )
            version_match = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
            if version_match:
                return int(version_match.group(1))
        else:
            result = subprocess.run(
                [brave_path, "--version"],
                capture_output=True, text=True, timeout=10
            )
            version_match = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
            if version_match:
                return int(version_match.group(1))
    except Exception:
        pass
    return None


def create_driver(brave_path):
    """Crea driver de Selenium con Brave + anti-detección."""
    log = get_logger()
    options = Options()
    options.binary_location = brave_path

    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--window-size=1400,900")

    brave_version = get_brave_version(brave_path)
    if brave_version:
        log.info(f"Brave versión: {brave_version}")
        service = Service(ChromeDriverManager(driver_version=str(brave_version)).install())
    else:
        log.warning("Brave versión no detectada. Usando latest.")
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def wait_for_login(driver):
    """Pausa para login manual."""
    print("")
    print("=" * 60)
    print("   PAUSA PARA LOGIN MANUAL")
    print("=" * 60)
    print("   1. Haz login manualmente en Instagram.")
    print("   2. Confirma que ves tu feed.")
    print("   3. Presiona Enter cuando estés listo.")
    print("=" * 60)
    input("\n   >>> Enter para continuar... ")
    get_logger().info("Login confirmado")


def extract_shortcodes_from_dom(driver):
    """Extrae shortcodes del DOM visible."""
    shortcodes = driver.execute_script("""
        const codes = new Set();
        const allLinks = document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]');
        allLinks.forEach(link => {
            const href = link.getAttribute('href') || '';
            const match = href.match(/\/(p|reel)\/([A-Za-z0-9_-]+)/);
            if (match) {
                codes.add(match[2]);
            }
        });
        return Array.from(codes);
    """)
    return set(shortcodes)


# =============================================================================
# SCRAPING - MODO NUEVOS
# =============================================================================

def get_known_shortcodes(db, username):
    """
    Obtiene todos los shortcodes que ya tenemos de un perfil.
    Para comparar y solo guardar nuevos.
    """
    rows = db.execute(
        "SELECT shortcode FROM memes WHERE source_profile = ?",
        (username,)
    ).fetchall()
    return {row['shortcode'] for row in rows}


def scrape_profile_nuevos(driver, username, scroll_count, scroll_delay, known_shortcodes):
    """
    Scrape ligero de un perfil: scrollea poco, retorna solo shortcodes NUEVOS.
    
    Optimización: Si en un scroll todos los shortcodes ya son conocidos,
    significa que ya pasamos los posts recientes. Early exit.
    """
    log = get_logger()
    url = f"https://www.instagram.com/{username}/"
    driver.get(url)

    try:
        WebDriverWait(driver, 12).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="/reel/"]'))
        )
    except Exception:
        log.warning(f"  No se pudo cargar @{username}. Saltando.")
        return set()

    time.sleep(3)

    all_shortcodes = set()
    all_new = set()
    consecutive_no_new = 0

    # Captura inicial
    initial = extract_shortcodes_from_dom(driver)
    all_shortcodes.update(initial)
    initial_new = initial - known_shortcodes
    all_new.update(initial_new)

    if not initial_new and len(initial) > 5:
        # Ya el primer vistazo no tiene nada nuevo
        log.info(f"  @{username}: 0 nuevos (primeros {len(initial)} ya conocidos). Skip.")
        return set()

    for i in range(scroll_count):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        delay = scroll_delay + random.uniform(0.5, 1.5)
        time.sleep(delay)

        # Simula humano
        driver.execute_script("window.scrollBy(0, -200);")
        time.sleep(0.5)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)

        current = extract_shortcodes_from_dom(driver)
        new_this_scroll = current - all_shortcodes
        all_shortcodes.update(current)

        truly_new = new_this_scroll - known_shortcodes
        all_new.update(truly_new)

        # Early exit: si scroll trajo posts pero TODOS ya conocidos
        if len(new_this_scroll) > 0 and len(truly_new) == 0:
            consecutive_no_new += 1
            if consecutive_no_new >= 2:
                log.debug(f"  @{username}: scroll {i+1} - solo conocidos. Parando.")
                break
        else:
            consecutive_no_new = 0

    return all_new


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Paso 1B: Scrape posts nuevos (multi-perfil)")
    parser.add_argument('--max-perfiles', type=int, default=None,
                        help="Límite de perfiles a visitar (default: todos)")
    parser.add_argument('--dry-run', action='store_true',
                        help="No guarda en DB, solo muestra")
    args = parser.parse_args()

    # Setup
    setup_logger('1b_scrape_nuevos')
    log = get_logger()
    config = load_config()
    scraping_cfg = get_section('scraping')

    # Health checks
    run_health_checks(checks=['config', 'db', 'dirs', 'cleanup'])

    # Parámetros
    perfiles = config.get('perfiles_target', [])
    scroll_count = scraping_cfg.get('scroll_count_nuevos', 3)
    scroll_delay = scraping_cfg.get('scroll_delay', 3.0)
    delay_entre_perfiles = scraping_cfg.get('delay_entre_perfiles', 5)
    brave_path = scraping_cfg.get('brave_path', '')
    is_dry_run = args.dry_run or config.get('dry_run', False)

    if not perfiles:
        log.error("No hay perfiles_target en config.json. Agrega al menos uno.")
        sys.exit(1)

    if args.max_perfiles:
        perfiles = perfiles[:args.max_perfiles]

    log.info(f"Perfiles a scrapear: {len(perfiles)}")
    log.info(f"Scrolls por perfil: {scroll_count}")
    log.info(f"Dry run: {is_dry_run}")

    # Rate limiter
    limiter = RateLimiter('instagram')
    if not limiter.can_request():
        log.error("Budget de Instagram agotado. Abortando.")
        sys.exit(1)

    # Inicializar DB
    init_db()
    db = get_db()

    # Pipeline run tracking
    run_id = uuid.uuid4().hex[:12]
    start_pipeline_run(run_id, '1b_scrape_nuevos')
    start_time = time.time()

    # Stats globales
    stats = {
        'perfiles_visitados': 0,
        'perfiles_con_nuevos': 0,
        'total_nuevos': 0,
        'perfiles_error': 0,
    }

    driver = None
    try:
        log.info("Iniciando Brave...")
        driver = create_driver(brave_path)

        # Login
        driver.get("https://www.instagram.com/")
        time.sleep(3)
        wait_for_login(driver)

        # Scrapear cada perfil
        for idx, username in enumerate(perfiles, 1):
            log.info(f"")
            log.info(f"[{idx}/{len(perfiles)}] @{username}")

            # Rate limit check
            if not limiter.can_request():
                log.warning("Budget de IG alcanzado. Deteniendo.")
                break

            try:
                # Obtener shortcodes conocidos de este perfil
                known = get_known_shortcodes(db, username)
                log.info(f"  Ya conocidos: {len(known)}")

                # Scrapear
                new_shortcodes = scrape_profile_nuevos(
                    driver, username, scroll_count, scroll_delay, known
                )

                stats['perfiles_visitados'] += 1
                limiter.log_request()

                if new_shortcodes:
                    stats['perfiles_con_nuevos'] += 1
                    stats['total_nuevos'] += len(new_shortcodes)
                    log.info(f"  +{len(new_shortcodes)} NUEVOS")

                    # Guardar en DB
                    for sc in new_shortcodes:
                        if is_dry_run:
                            print(f"    [DRY] {sc}")
                        else:
                            insert_meme(
                                shortcode=sc,
                                source_profile=username,
                                source_type='desconocido'
                            )
                        track_item('processed')
                else:
                    log.info(f"  Sin posts nuevos")
                    track_item('skipped')

            except Exception as e:
                log.error(f"  Error en @{username}: {e}")
                stats['perfiles_error'] += 1
                track_item('error')

            # Delay entre perfiles (evitar rate limit)
            if idx < len(perfiles):
                jitter = random.uniform(0.5, 2.0)
                time.sleep(delay_entre_perfiles + jitter)

    except KeyboardInterrupt:
        log.warning("Interrumpido por usuario")
    except Exception as e:
        log.error(f"Error fatal: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            log.info("Navegador cerrado")

    # Registrar fin del run
    duration = time.time() - start_time
    finish_pipeline_run(
        run_id, '1b_scrape_nuevos',
        status='success',
        items_processed=stats['total_nuevos'],
        items_skipped=stats['perfiles_visitados'] - stats['perfiles_con_nuevos'],
        items_error=stats['perfiles_error'],
        duration_s=round(duration, 2)
    )

    # Resumen final
    log.info("")
    log.info("=" * 60)
    log.info("   RESUMEN - SCRAPE NUEVOS")
    log.info("=" * 60)
    log.info(f"   Perfiles visitados:    {stats['perfiles_visitados']}/{len(perfiles)}")
    log.info(f"   Perfiles con nuevos:   {stats['perfiles_con_nuevos']}")
    log.info(f"   Total posts nuevos:    {stats['total_nuevos']}")
    log.info(f"   Errores:               {stats['perfiles_error']}")
    log.info(f"   Duración:              {duration:.1f}s")
    if is_dry_run:
        log.info(f"   [DRY RUN - nada guardado]")
    log.info("=" * 60)

    # Telegram notification (si hay nuevos)
    if stats['total_nuevos'] > 0 and not is_dry_run:
        send_notification(
            f"📥 *Scrape completado*\n"
            f"+{stats['total_nuevos']} posts nuevos "
            f"de {stats['perfiles_con_nuevos']} perfiles",
            silent=True
        )

    log_summary()


if __name__ == "__main__":
    main()
