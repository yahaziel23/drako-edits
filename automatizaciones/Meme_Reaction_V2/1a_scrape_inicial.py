#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Paso 1A: Scrape Inicial (Un Perfil Completo)

Primera vez que agregas un perfil: scrapea TODOS los posts del grid.
Abre Brave visible, pausa para login manual, scrollea muchas veces,
captura shortcodes y los registra en SQLite como 'por_descargar'.

Uso:
    python 1a_scrape_inicial.py --perfil elmello2023
    python 1a_scrape_inicial.py --perfil elmello2023 --scrolls 30
    python 1a_scrape_inicial.py --perfil elmello2023 --dry-run

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

from utils.db import init_db, get_db, insert_meme, get_meme
from utils.config import load_config, get_section
from utils.logger import setup_logger, get_logger, track_item, log_summary
from utils.health import run_health_checks
from utils.rate_limiter import RateLimiter


# =============================================================================
# SELENIUM HELPERS
# =============================================================================

def get_brave_version(brave_path):
    """Detecta versión major de Brave via PowerShell (Windows)."""
    try:
        if sys.platform == "win32":
            ps_cmd = (
                'powershell -Command "'
                f"(Get-Item '{brave_path}').VersionInfo.FileVersion"
                '"'
            )
            result = subprocess.run(
                ps_cmd, capture_output=True, text=True,
                shell=True, timeout=15
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

    # Anti-detección
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--window-size=1400,900")

    # ChromeDriver compatible con Brave
    brave_version = get_brave_version(brave_path)
    if brave_version:
        log.info(f"Brave versión detectada: {brave_version}")
        service = Service(ChromeDriverManager(driver_version=str(brave_version)).install())
    else:
        log.warning("No se pudo detectar versión de Brave. Fallback: latest")
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def wait_for_login(driver):
    """Pausa para login manual de Instagram."""
    log = get_logger()
    print("")
    print("=" * 60)
    print("   PAUSA PARA LOGIN MANUAL")
    print("=" * 60)
    print("   El navegador está abierto en Instagram.")
    print("   1. Haz login manualmente si te lo pide.")
    print("   2. Confirma que ves tu feed/home.")
    print("   3. Presiona Enter aquí cuando estés listo.")
    print("=" * 60)
    input("\n   >>> Presiona Enter para continuar... ")
    log.info("Login confirmado por usuario")


# =============================================================================
# SCRAPING LOGIC
# =============================================================================

def extract_shortcodes_from_dom(driver):
    """
    Extrae TODOS los shortcodes visibles en el DOM.
    Busca /p/XXXXX y /reel/XXXXX (IG usa ambos indistintamente).
    """
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


def scroll_and_collect(driver, scroll_count, scroll_delay):
    """
    Scrollea la página y captura shortcodes EN CADA SCROLL.
    Instagram virtualiza el DOM: links desaparecen al salir del viewport.
    """
    log = get_logger()
    all_shortcodes = set()

    # Capturar lo visible antes de scrollear
    initial = extract_shortcodes_from_dom(driver)
    all_shortcodes.update(initial)
    log.info(f"Antes de scroll: {len(initial)} shortcodes")

    no_new_count = 0

    for i in range(scroll_count):
        # Scroll hasta abajo
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        delay = scroll_delay + random.uniform(1.0, 2.5)
        time.sleep(delay)

        # Simula humano: sube un poco y vuelve
        driver.execute_script("window.scrollBy(0, -300);")
        time.sleep(0.7)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        # Capturar shortcodes del DOM actual
        current = extract_shortcodes_from_dom(driver)
        new_this_scroll = current - all_shortcodes
        all_shortcodes.update(current)

        log.info(f"  Scroll {i+1}/{scroll_count}: +{len(new_this_scroll)} nuevos (total: {len(all_shortcodes)})")

        # Early stop si no hay nuevos en 3 scrolls consecutivos
        if len(new_this_scroll) == 0:
            no_new_count += 1
            if no_new_count >= 3 and i > 5:
                log.info("  Sin nuevos en 3 scrolls consecutivos. Fin del grid.")
                break
        else:
            no_new_count = 0

    return all_shortcodes


def scrape_profile_inicial(driver, username, scroll_count, scroll_delay):
    """
    Scrape completo de un perfil. Retorna set de shortcodes.
    """
    log = get_logger()
    url = f"https://www.instagram.com/{username}/"
    log.info(f"Navegando a: {url}")
    driver.get(url)

    # Esperar carga
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="/reel/"]'))
        )
        log.info("Página cargada")
    except Exception:
        log.error(f"No se pudo cargar @{username}. Verifica login y que el perfil exista.")
        return set()

    # Espera extra para render completo
    time.sleep(4)

    # Scrollear y capturar
    log.info(f"Scrolleando grid ({scroll_count} scrolls, {scroll_delay}s delay)...")
    all_shortcodes = scroll_and_collect(driver, scroll_count, scroll_delay)

    log.info(f"Total shortcodes capturados de @{username}: {len(all_shortcodes)}")
    return all_shortcodes


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Paso 1A: Scrape inicial de un perfil completo")
    parser.add_argument('--perfil', '-p', required=True, help="Username de IG (sin @)")
    parser.add_argument('--scrolls', '-s', type=int, default=None,
                        help="Número de scrolls (default: config.json scroll_count_inicial)")
    parser.add_argument('--dry-run', action='store_true',
                        help="Solo muestra shortcodes, no guarda en DB")
    args = parser.parse_args()

    # Setup
    setup_logger('1a_scrape_inicial')
    log = get_logger()
    config = load_config()
    scraping_cfg = get_section('scraping')

    # Health checks (sin brave check mandatorio aquí, lo verificamos al crear driver)
    run_health_checks(checks=['config', 'db', 'dirs', 'cleanup'])

    # Parámetros
    username = args.perfil.lstrip('@')
    scroll_count = args.scrolls or scraping_cfg.get('scroll_count_inicial', 20)
    scroll_delay = scraping_cfg.get('scroll_delay', 3.0)
    brave_path = scraping_cfg.get('brave_path', '')
    is_dry_run = args.dry_run or config.get('dry_run', False)

    log.info(f"Perfil: @{username}")
    log.info(f"Scrolls: {scroll_count}")
    log.info(f"Dry run: {is_dry_run}")

    # Rate limiter (IG)
    limiter = RateLimiter('instagram')
    if not limiter.can_request():
        log.error("Budget de Instagram agotado por hoy. Abortando.")
        sys.exit(1)

    # Inicializar DB
    init_db()
    db = get_db()

    # Verificar cuántos ya tenemos de este perfil
    existing = db.execute(
        "SELECT COUNT(*) as cnt FROM memes WHERE source_profile = ?",
        (username,)
    ).fetchone()
    if existing and existing['cnt'] > 0:
        log.warning(f"Ya hay {existing['cnt']} posts de @{username} en DB.")
        log.warning("Los duplicados se ignorarán automáticamente (INSERT OR IGNORE).")

    # Crear driver y scrapear
    driver = None
    try:
        log.info("Iniciando Brave...")
        driver = create_driver(brave_path)

        # Navegar a IG para login
        driver.get("https://www.instagram.com/")
        time.sleep(3)
        wait_for_login(driver)

        # Scrapear perfil
        shortcodes = scrape_profile_inicial(driver, username, scroll_count, scroll_delay)

        if not shortcodes:
            log.warning("No se capturaron shortcodes. Verifica el perfil.")
            return

        # Registrar en SQLite
        new_count = 0
        skip_count = 0

        for sc in shortcodes:
            if is_dry_run:
                print(f"  [DRY] {sc}")
                new_count += 1
            else:
                was_new = insert_meme(
                    shortcode=sc,
                    source_profile=username,
                    source_type='desconocido'  # Se determina en paso 2
                )
                if was_new:
                    new_count += 1
                    track_item('processed')
                else:
                    skip_count += 1
                    track_item('skipped')

        # Log request a IG
        limiter.log_request()

        # Resumen
        log.info("")
        log.info("=" * 50)
        log.info(f"RESULTADO - @{username}")
        log.info(f"  Shortcodes capturados: {len(shortcodes)}")
        log.info(f"  Nuevos en DB:          {new_count}")
        log.info(f"  Ya existían (skip):    {skip_count}")
        if is_dry_run:
            log.info(f"  [DRY RUN - nada guardado]")
        log.info("=" * 50)

    except KeyboardInterrupt:
        log.warning("Interrumpido por usuario")
    except Exception as e:
        log.error(f"Error inesperado: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
            log.info("Navegador cerrado")

    # Resumen final de métricas
    log_summary()


if __name__ == "__main__":
    main()
