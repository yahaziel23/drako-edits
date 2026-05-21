#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 1: Scraping de Links con Selenium (Brave)

Abre Brave visible → navega a perfiles de IG → pausa para login manual
→ scrollea → extrae links de posts tipo foto → guarda shortcodes nuevos.

Navegador: Brave (Chromium-based, usa ChromeDriver)
Login: MANUAL — Selenium pausa y espera que el usuario haga login si es necesario.

Output: historial/links_scrapeados.json

Uso:
    python 1_scrape_meme_links.py

Dependencias: selenium, webdriver-manager
"""

import json
import sys
import time
import re
import subprocess
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
HISTORIAL_DIR = SCRIPT_DIR / "historial"
LINKS_FILE = HISTORIAL_DIR / "links_scrapeados.json"

# --- BRAVE ---
# Cambiar si tu Brave está en otra ruta
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
# Mac: "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

# --- PERFILES TARGET ---
# TODO: Mover a config.json cuando exista
PERFILES_TARGET = [
    "elmello2023",
]

# --- SCRAPING ---
SCROLL_COUNT = 5          # Cuántas veces scrollear para cargar más posts
SCROLL_DELAY = 2.5        # Segundos entre scrolls (random se suma)
DELAY_ENTRE_PERFILES = 5  # Segundos entre perfiles


# =============================================================================
# FUNCIONES
# =============================================================================

def get_brave_version():
    """
    Detecta la versión major de Brave automáticamente.
    En Windows: usa PowerShell para leer la versión del .exe
    En otros: usa --version flag
    """
    try:
        if sys.platform == "win32":
            # PowerShell: leer FileVersion del ejecutable
            ps_cmd = (
                'powershell -Command "'
                f"(Get-Item '{BRAVE_PATH}').VersionInfo.FileVersion"
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
            # Mac/Linux: --version funciona normal
            result = subprocess.run(
                [BRAVE_PATH, "--version"],
                capture_output=True, text=True, timeout=10
            )
            version_match = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
            if version_match:
                return int(version_match.group(1))
    except Exception:
        pass

    return None


def load_historial():
    """Carga historial de links ya scrapeados."""
    if LINKS_FILE.exists():
        try:
            data = json.loads(LINKS_FILE.read_text(encoding="utf-8"))
            return data
        except Exception:
            pass
    return {"scrapeados": [], "por_descargar": []}


def save_historial(data):
    """Guarda historial."""
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    LINKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_driver():
    """
    Crea el driver de Selenium con Brave.
    Abre Brave VISIBLE (no headless) para permitir login manual.
    Detecta versión de Brave para descargar ChromeDriver compatible.
    """
    options = Options()
    options.binary_location = BRAVE_PATH

    # NO headless — necesitamos ver el browser para login manual
    # options.add_argument("--headless=new")

    # Evitar detección básica de bots
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Ventana grande para ver bien el grid
    options.add_argument("--window-size=1400,900")

    # Detectar versión de Brave y descargar ChromeDriver compatible
    brave_version = get_brave_version()
    if brave_version:
        print(f"   Brave versión detectada: {brave_version}")
        service = Service(ChromeDriverManager(driver_version=str(brave_version)).install())
    else:
        print("   [!] No se pudo detectar versión de Brave.")
        print("       Intentando con versión hardcodeada 148...")
        print("       Si falla, edita BRAVE_VERSION_FALLBACK en este archivo.")
        # Fallback hardcodeado — cambiar si actualizas Brave
        BRAVE_VERSION_FALLBACK = "148"
        service = Service(ChromeDriverManager(driver_version=BRAVE_VERSION_FALLBACK).install())

    driver = webdriver.Chrome(service=service, options=options)

    # Quitar la propiedad navigator.webdriver
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    return driver


def wait_for_login(driver):
    """
    Pausa para login manual.
    El usuario hace login en el browser y luego presiona Enter en la terminal.
    """
    print("")
    print("=" * 60)
    print("   PAUSA PARA LOGIN MANUAL")
    print("=" * 60)
    print("   El navegador está abierto.")
    print("   1. Si Instagram te pide login, hazlo manualmente en el browser.")
    print("   2. Si ya estás loggeado, simplemente continúa.")
    print("   3. Cuando estés listo, presiona Enter aquí.")
    print("=" * 60)
    input("\n   >>> Presiona Enter para continuar... ")
    print("   [OK] Continuando...")
    print("")


def scroll_page(driver, times=SCROLL_COUNT):
    """Scrollea la página para cargar más posts."""
    import random
    for i in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        delay = SCROLL_DELAY + random.uniform(0.5, 2.0)
        print(f"      Scroll {i+1}/{times} (esperando {delay:.1f}s)")
        time.sleep(delay)


def extract_post_links(driver):
    """
    Extrae todos los links de posts del grid actual.
    Retorna lista de shortcodes.
    """
    links = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/p/"]')

    shortcodes = set()
    for link in links:
        href = link.get_attribute("href")
        if href:
            match = re.search(r'/p/([A-Za-z0-9_-]+)', href)
            if match:
                shortcodes.add(match.group(1))

    return list(shortcodes)


def filter_photos_only(driver, shortcodes):
    """
    Filtra shortcodes para quedarse solo con fotos (no videos/reels).
    
    En el grid de IG, los posts con video tienen un SVG overlay.
    Los posts solo-foto no tienen overlay.
    """
    photo_shortcodes = []
    video_shortcodes = []

    for sc in shortcodes:
        try:
            link_el = driver.find_element(By.CSS_SELECTOR, f'a[href*="/p/{sc}/"]')
            svgs = link_el.find_elements(By.TAG_NAME, "svg")

            is_video = False
            for svg in svgs:
                aria = svg.get_attribute("aria-label") or ""
                if any(word in aria.lower() for word in ["reel", "video", "clip"]):
                    is_video = True
                    break

            if is_video:
                video_shortcodes.append(sc)
            else:
                photo_shortcodes.append(sc)

        except Exception:
            photo_shortcodes.append(sc)

    return photo_shortcodes, video_shortcodes


def scrape_profile(driver, username, historial):
    """
    Scrapes un perfil y retorna shortcodes nuevos de fotos.
    """
    url = f"https://www.instagram.com/{username}/"
    print(f"\n   Navegando a: {url}")
    driver.get(url)

    # Esperar que cargue el grid
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/p/"]'))
        )
        print("   [OK] Grid cargado.")
    except Exception:
        print(f"   [X] No se pudo cargar el grid de @{username}.")
        print("       Puede que necesites hacer login o el perfil no existe.")
        return []

    # Scrollear para cargar más posts
    print(f"   Scrolleando ({SCROLL_COUNT} veces)...")
    scroll_page(driver)

    # Extraer links
    all_shortcodes = extract_post_links(driver)
    print(f"   Links encontrados: {len(all_shortcodes)}")

    # Filtrar solo fotos
    photo_scs, video_scs = filter_photos_only(driver, all_shortcodes)
    print(f"   Fotos: {len(photo_scs)} | Videos/Reels: {len(video_scs)}")

    # Filtrar ya scrapeados
    ya_scrapeados = set(historial.get("scrapeados", []))
    nuevos = [sc for sc in photo_scs if sc not in ya_scrapeados]
    print(f"   Nuevos (no scrapeados antes): {len(nuevos)}")

    return nuevos


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def main():
    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 1: SCRAPING DE LINKS")
    print(SEPARATOR_EQ)
    print(f"   Perfiles target: {PERFILES_TARGET}")
    print(f"   Scrolls por perfil: {SCROLL_COUNT}")
    print(f"   Historial: {LINKS_FILE}")

    # Verificar que Brave existe
    if not Path(BRAVE_PATH).exists():
        print(f"\n   [X] No se encontró Brave en: {BRAVE_PATH}")
        print("       Edita BRAVE_PATH en este archivo.")
        return

    # Cargar historial
    historial = load_historial()
    print(f"   Links previos en historial: {len(historial.get('scrapeados', []))}")
    print(f"   Pendientes de descargar: {len(historial.get('por_descargar', []))}")

    # Crear driver
    print("\n   Abriendo Brave...")
    driver = create_driver()

    try:
        # Navegar a Instagram primero
        driver.get("https://www.instagram.com/")
        time.sleep(3)

        # Pausa para login manual
        wait_for_login(driver)

        # Scrapeear cada perfil
        todos_nuevos = []
        for i, username in enumerate(PERFILES_TARGET):
            print("")
            print(SEPARATOR)
            print(f"   PERFIL {i+1}/{len(PERFILES_TARGET)}: @{username}")
            print(SEPARATOR)

            nuevos = scrape_profile(driver, username, historial)
            todos_nuevos.extend(nuevos)

            if i < len(PERFILES_TARGET) - 1:
                print(f"\n   Esperando {DELAY_ENTRE_PERFILES}s antes del siguiente perfil...")
                time.sleep(DELAY_ENTRE_PERFILES)

        # Actualizar historial
        historial["scrapeados"] = list(set(historial.get("scrapeados", []) + todos_nuevos))
        historial["por_descargar"] = list(set(historial.get("por_descargar", []) + todos_nuevos))
        save_historial(historial)

        # Resumen
        print("")
        print(SEPARATOR_EQ)
        print("   RESUMEN")
        print(SEPARATOR_EQ)
        print(f"   Nuevos links encontrados: {len(todos_nuevos)}")
        print(f"   Total en historial: {len(historial['scrapeados'])}")
        print(f"   Pendientes de descargar: {len(historial['por_descargar'])}")
        print(f"   Guardado en: {LINKS_FILE}")
        print(SEPARATOR_EQ)

        if todos_nuevos:
            print("\n   Primeros 5 nuevos:")
            for sc in todos_nuevos[:5]:
                print(f"     - https://www.instagram.com/p/{sc}/")

    finally:
        print("\n   Cerrando navegador...")
        driver.quit()
        print("   [OK] Listo.")


if __name__ == "__main__":
    main()
