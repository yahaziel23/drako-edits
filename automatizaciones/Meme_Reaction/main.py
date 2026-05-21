#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction - Pipeline Automatizado (main.py)

Orquestador principal. Ejecuta:
1. pip install de requirements.txt (solo la primera vez o si cambian deps)
2. Los pasos numerados en orden:
   1_ scrape_meme_links
   2_ download_memes
   3_ classify_meme
   4_ match_clip
   5_ verify_match
   6_ generate_caption
   7_ generate_video
   8_ save_config

.env: Usa el del proyecto general (../../.env)

Uso:
    python automatizaciones/Meme_Reaction/main.py
"""

import subprocess
import sys
import os
from pathlib import Path

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # drako-edits/
REQUIREMENTS = SCRIPT_DIR / "requirements.txt"
ENV_FILE = PROJECT_ROOT / ".env"  # .env del proyecto general

# Pasos en orden de ejecución
STEPS = [
    "1_scrape_meme_links.py",
    "2_download_memes.py",
    "3_classify_meme.py",
    "4_match_clip.py",
    "5_verify_match.py",
    "6_generate_caption.py",
    "7_generate_video.py",
    "8_save_config.py",
]


# =============================================================================
# FUNCIONES
# =============================================================================

def install_requirements():
    """Instala dependencias del sub-proyecto."""
    print("\n" + "=" * 60)
    print("   MEME REACTION - INSTALANDO DEPENDENCIAS")
    print("=" * 60)
    print(f"   requirements.txt: {REQUIREMENTS}")

    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS), "--quiet"],
        capture_output=True, text=True
    )

    if result.returncode == 0:
        print("   [OK] Dependencias instaladas.")
    else:
        print(f"   [X] Error instalando dependencias:")
        print(f"   {result.stderr[:500]}")
        sys.exit(1)


def load_env():
    """Carga variables de entorno del .env general."""
    if ENV_FILE.exists():
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
        print(f"   [OK] .env cargado: {ENV_FILE}")
    else:
        print(f"   [!] No se encontró .env en: {ENV_FILE}")
        print(f"       Las credenciales deben estar en variables de entorno.")


def run_step(step_file):
    """
    Ejecuta un paso del pipeline.
    Retorna True si fue exitoso, False si falló.
    """
    step_path = SCRIPT_DIR / step_file

    if not step_path.exists():
        print(f"   [!] {step_file} no existe todavía. Saltando.")
        return False

    print(f"\n{'─' * 60}")
    print(f"   EJECUTANDO: {step_file}")
    print(f"{'─' * 60}")

    result = subprocess.run(
        [sys.executable, str(step_path)],
        cwd=str(SCRIPT_DIR)
    )

    if result.returncode == 0:
        print(f"   [OK] {step_file} completado.")
        return True
    else:
        print(f"   [X] {step_file} falló (exit code: {result.returncode})")
        return False


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   MEME REACTION - PIPELINE AUTOMATIZADO")
    print("=" * 60)
    print(f"   Directorio: {SCRIPT_DIR}")
    print(f"   Proyecto:   {PROJECT_ROOT}")

    # 1. Instalar dependencias
    install_requirements()

    # 2. Cargar .env
    load_env()

    # 3. Ejecutar pasos en orden
    print("\n" + "=" * 60)
    print("   EJECUTANDO PIPELINE")
    print("=" * 60)

    results = {}
    for step in STEPS:
        success = run_step(step)
        results[step] = success

        # Si un paso falla, preguntar si continuar
        if not success:
            # Por ahora, si no existe el archivo simplemente salta
            # Cuando estén implementados, aquí se puede decidir si parar
            pass

    # Resumen
    print("\n" + "=" * 60)
    print("   RESUMEN DEL PIPELINE")
    print("=" * 60)
    for step, success in results.items():
        status = "[OK]" if success else "[--]"
        print(f"   {status} {step}")
    print("=" * 60)
