#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 1: Scraping de Links con Selenium (Brave)

Abre Brave visible → navega a perfiles de IG → pausa para login manual
→ scrollea → captura TODOS los shortcodes del grid → guarda en historial.

IMPORTANTE:
- Instagram usa /reel/ para CASI TODO en el grid (incluso fotos)
- Instagram virtualiza el DOM (links desaparecen al scrollear)
- Por eso capturamos shortcodes DURANTE el scroll, no solo al final
- NO filtramos fotos vs videos aquí (imposible con el DOM actual)
- El Paso 2 (instaloader) determina si es foto o video y descarga solo fotos

Output: historial/links_scrapeados.json

Uso:
    python 1_scrape_meme_links.py

Dependencias: selenium, webdriver-manager
"""

import json
import sys
import time
import re
import random
import subprocess
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
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
BRAVE_PATH = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"

# --- PERFILES TARGET ---
PERFILES_TARGET = [
    "elmello2023",
]

# --- SCRAPING ---
SCROLL_COUNT = 8          # Cuántas veces scrollear (más = más posts)
SCROLL_DELAY = 3.0        # Segundos base entre scrolls
DELAY_ENTRE_PERFILES = 5  # Segundos entre perfiles


# =============================================================================
# FUNCIONES
# =============================================================================

def get_brave_version():
    """Detecta versión major de Brave via PowerShell (Windows)."""
    try:
        if sys.platform == "win32":
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
            return json.loads(LINKS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"scrapeados": [], "por_descargar": []}


def save_historial(data):
    """Guarda historial."""
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    LINKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_driver():
    """Crea driver de Selenium con Brave."""
    options = Options()
    options.binary_location = BRAVE_PATH

    # Anti-detección
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--window-size=1400,900")

    # ChromeDriver compatible con Brave
    brave_version = get_brave_version()
    if brave_version:
        print(f"   Brave versión detectada: {brave_version}")
        service = Service(ChromeDriverManager(driver_version=str(brave_version)).install())
    else:
        print("   [!] No se pudo detectar versión de Brave. Fallback: 148")
        service = Service(ChromeDriverManager(driver_version="148").install())

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def wait_for_login(driver):
    """Pausa para login manual."""
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
    print("   [OK] Continuando...")
    print("")


def extract_shortcodes_from_dom(driver):
    """
    Extrae TODOS los shortcodes visibles en el DOM en este momento.
    Busca tanto /p/XXXXX como /reel/XXXXX (IG usa ambos indistintamente).
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


def scroll_and_collect(driver, times=SCROLL_COUNT):
    """
    Scrollea la página y captura shortcodes EN CADA SCROLL.
    
    Instagram virtualiza el DOM (los links desaparecen al salir del viewport),
    así que capturamos shortcodes después de cada scroll y los acumulamos.
    """
    all_shortcodes = set()

    # Capturar lo que hay antes de scrollear
    initial = extract_shortcodes_from_dom(driver)
    all_shortcodes.update(initial)
    print(f"   Antes de scroll: {len(initial)} shortcodes")

    for i in range(times):
        # Scroll hasta abajo
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        delay = SCROLL_DELAY + random.uniform(1.0, 2.5)
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

        print(f"      Scroll {i+1}/{times}: +{len(new_this_scroll)} nuevos (total acumulado: {len(all_shortcodes)})")

        # Si no hay nuevos en 2 scrolls seguidos, puede que sea el fin
        if len(new_this_scroll) == 0 and i > 2:
            print("      [!] Sin nuevos. Probablemente se acabó el contenido.")

    return all_shortcodes


def scrape_profile(driver, username, historial):
    """
    Scrapes un perfil y retorna shortcodes nuevos.
    NO filtra fotos vs videos (eso lo hace el Paso 2 con instaloader).
    """
    url = f"https://www.instagram.com/{username}/"
    print(f"\n   Navegando a: {url}")
    driver.get(url)

    # Esperar que cargue algo
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/p/"], a[href*="/reel/"]'))
        )
        print("   [OK] Página cargada.")
    except Exception:
        print(f"   [X] No se pudo cargar @{username}.")
        print("       Verifica login y que el perfil exista.")
        return []

    # Espera extra para render completo
    time.sleep(4)

    # Scrollear y capturar
    print(f"   Scrolleando y capturando ({SCROLL_COUNT} scrolls)...")
    all_shortcodes = scroll_and_collect(driver)

    print(f"\n   Total shortcodes capturados: {len(all_shortcodes)}")

    # Filtrar ya scrapeados
    ya_scrapeados = set(historial.get("scrapeados", []))
    nuevos = [sc for sc in all_shortcodes if sc not in ya_scrapeados]
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
    print("   Nota: Captura TODOS los shortcodes (fotos+videos).")
    print("         El Paso 2 filtrará solo fotos con instaloader.")

    # Verificar Brave
    if not Path(BRAVE_PATH).exists():
        print(f"\n   [X] No se encontró Brave en: {BRAVE_PATH}")
        return

    # Cargar historial
    historial = load_historial()
    print(f"   Links previos en historial: {len(historial.get('scrapeados', []))}")
    print(f"   Pendientes de descargar: {len(historial.get('por_descargar', []))}")

    # Crear driver
    print("\n   Abriendo Brave...")
    driver = create_driver()

    try:
        # Navegar a Instagram
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
                print(f"\n   Esperando {DELAY_ENTRE_PERFILES}s...")
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
        print(f"   Nuevos shortcodes encontrados: {len(todos_nuevos)}")
        print(f"   Total en historial: {len(historial['scrapeados'])}")
        print(f"   Pendientes de descargar: {len(historial['por_descargar'])}")
        print(f"   Guardado en: {LINKS_FILE}")
        print(SEPARATOR_EQ)

        if todos_nuevos:
            print("\n   Primeros 10:")
            for sc in todos_nuevos[:10]:
                print(f"     - https://www.instagram.com/p/{sc}/")
            if len(todos_nuevos) > 10:
                print(f"     ... y {len(todos_nuevos) - 10} más")

    finally:
        print("\n   Cerrando navegador...")
        driver.quit()
        print("   [OK] Listo.")


if __name__ == "__main__":
    main()
