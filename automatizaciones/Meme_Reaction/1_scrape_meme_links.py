#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 1: Scraping de Links con Selenium (Brave)

Abre Brave visible → navega a perfiles de IG → pausa para login manual
→ scrollea → extrae links de posts tipo FOTO SIMPLE → guarda shortcodes nuevos.

Filtro:
- Solo fotos simples (sin overlay icons)
- Videos/Reels tienen SVG de play → skip
- Carousels tienen SVG de múltiples páginas → skip
- Regla: si el link del grid tiene CUALQUIER SVG dentro → no es foto simple → skip

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
SCROLL_COUNT = 5          # Cuántas veces scrollear
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


def scroll_page(driver, times=SCROLL_COUNT):
    """Scrollea la página para cargar más posts."""
    prev_count = 0
    for i in range(times):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        delay = SCROLL_DELAY + random.uniform(1.0, 2.5)
        print(f"      Scroll {i+1}/{times} (esperando {delay:.1f}s)...", end="")
        time.sleep(delay)

        # Simula humano: sube un poco y vuelve a bajar
        driver.execute_script("window.scrollBy(0, -200);")
        time.sleep(0.8)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.5)

        # Contar links para ver progreso
        current_count = driver.execute_script(
            "return document.querySelectorAll('a[href*=\"/p/\"]').length;"
        )
        print(f" ({current_count} links en DOM)")

        if current_count == prev_count and i > 1:
            print("      [!] No cargaron más links.")
        prev_count = current_count


def extract_and_filter_posts(driver):
    """
    Extrae posts del grid y los clasifica usando JavaScript.
    
    Regla de filtrado:
    - Fotos simples: el <a> del grid NO tiene ningún <svg> dentro
    - Videos/Reels: tienen SVG con icono de play (triángulo)
    - Carousels: tienen SVG con icono de múltiples páginas
    - Regla simplificada: tiene SVG = skip, no tiene SVG = foto simple
    
    Returns:
        tuple: (fotos_simples, con_svg_overlay)
            Cada uno es una lista de shortcodes
    """
    result = driver.execute_script("""
        const fotos = [];
        const otros = [];
        
        // Obtener todos los links /p/ de la página
        const allLinks = document.querySelectorAll('a[href*="/p/"]');
        
        allLinks.forEach(link => {
            const href = link.getAttribute('href') || '';
            const match = href.match(/\/p\/([A-Za-z0-9_-]+)/);
            if (!match) return;
            
            const shortcode = match[1];
            
            // Buscar SVGs dentro del link
            // Fotos simples: 0 SVGs overlay
            // Videos: tienen SVG (play icon)
            // Carousels: tienen SVG (multi-page icon)
            const svgs = link.querySelectorAll('svg');
            
            if (svgs.length === 0) {
                fotos.push(shortcode);
            } else {
                otros.push(shortcode);
            }
        });
        
        return {fotos: fotos, otros: otros};
    """)

    fotos = result.get("fotos", [])
    otros = result.get("otros", [])
    return fotos, otros


def debug_page_state(driver):
    """
    Imprime información de debug sobre el estado de la página.
    Se activa cuando se encuentran muy pocos posts.
    """
    print("")
    print("   " + "~" * 50)
    print("   DEBUG: Analizando DOM de la página")
    print("   " + "~" * 50)

    # Total de <a> en la página
    total_a = driver.execute_script("return document.querySelectorAll('a').length;")
    print(f"   Total de <a> en la página: {total_a}")

    # Links con /p/
    p_links = driver.execute_script("""
        const links = document.querySelectorAll('a[href*="/p/"]');
        return Array.from(links).map(a => {
            const svgCount = a.querySelectorAll('svg').length;
            return {href: a.href, svgs: svgCount, text: a.textContent.slice(0, 30)};
        });
    """)
    print(f"   Links con /p/: {len(p_links)}")
    for item in p_links[:15]:
        print(f"     {item['href']} (SVGs: {item['svgs']})")

    # Links con /reel/
    reel_links = driver.execute_script("""
        const links = document.querySelectorAll('a[href*="/reel/"]');
        return Array.from(links).map(a => a.href);
    """)
    if reel_links:
        print(f"   Links con /reel/: {len(reel_links)}")
        for h in reel_links[:5]:
            print(f"     {h}")

    # Buscar el grid principal (article)
    articles = driver.execute_script("return document.querySelectorAll('article').length;")
    print(f"   <article> elements: {articles}")

    # Buscar por la estructura del grid de IG
    grid_items = driver.execute_script("""
        // Intentar encontrar el contenedor del grid
        // Instagram suele usar un div con role='tabpanel' o similar
        const mainContent = document.querySelector('main') || document.body;
        const allLinks = mainContent.querySelectorAll('a');
        const igLinks = [];
        allLinks.forEach(a => {
            const href = a.getAttribute('href') || '';
            if (href.startsWith('/p/') || href.startsWith('/reel/')) {
                igLinks.push(href);
            }
        });
        return igLinks;
    """)
    print(f"   Links relativos /p/ o /reel/ en <main>: {len(grid_items)}")
    for h in grid_items[:15]:
        print(f"     {h}")

    print("   " + "~" * 50)
    print("")


def scrape_profile(driver, username, historial):
    """
    Scrapes un perfil y retorna shortcodes nuevos de fotos simples.
    """
    url = f"https://www.instagram.com/{username}/"
    print(f"\n   Navegando a: {url}")
    driver.get(url)

    # Esperar que cargue - buscar links /p/ O cualquier article
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/p/"], article'))
        )
        print("   [OK] Página cargada.")
    except Exception:
        print(f"   [X] No se pudo cargar @{username}.")
        print("       Verifica login y que el perfil exista.")
        return []

    # Espera extra para render completo
    time.sleep(4)

    # Contar posts iniciales
    initial_count = driver.execute_script(
        "return document.querySelectorAll('a[href*=\"/p/\"]').length;"
    )
    print(f"   Posts /p/ visibles inicialmente: {initial_count}")

    # Si hay 0 o muy pocos, activar debug antes de scrollear
    if initial_count <= 3:
        print("   [!] Muy pocos posts detectados. Activando debug...")
        debug_page_state(driver)

    # Scrollear
    print(f"   Scrolleando ({SCROLL_COUNT} veces)...")
    scroll_page(driver)

    # Espera final
    time.sleep(2)

    # Extraer y filtrar
    fotos_simples, otros = extract_and_filter_posts(driver)

    print(f"   Resultado:")
    print(f"     Fotos simples (sin SVG overlay): {len(fotos_simples)}")
    print(f"     Videos/Carousels (con SVG overlay): {len(otros)}")

    # Si hay pocos resultados totales, debug
    if len(fotos_simples) + len(otros) <= 3:
        debug_page_state(driver)

    # Filtrar ya scrapeados
    ya_scrapeados = set(historial.get("scrapeados", []))
    nuevos = [sc for sc in fotos_simples if sc not in ya_scrapeados]
    print(f"     Nuevos (no scrapeados antes): {len(nuevos)}")

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
    print(f"   Filtro: SOLO fotos simples (sin SVG = sin icono video/carousel)")

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
        print(f"   Nuevos links encontrados: {len(todos_nuevos)}")
        print(f"   Total en historial: {len(historial['scrapeados'])}")
        print(f"   Pendientes de descargar: {len(historial['por_descargar'])}")
        print(f"   Guardado en: {LINKS_FILE}")
        print(SEPARATOR_EQ)

        if todos_nuevos:
            print("\n   Links nuevos:")
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
