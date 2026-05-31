#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Health Checks Module

Verificaciones pre-ejecución para detectar problemas antes de
desperdiciar tiempo o gastar tokens.

Uso:
    from utils.health import run_health_checks
    
    # Al inicio de cualquier script:
    run_health_checks()  # Exit(1) si algo crítico falla
    
    # Solo checks específicos:
    run_health_checks(checks=['config', 'db', 'env'])
"""

import os
import sys
import shutil
from pathlib import Path

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent  # Meme_Reaction_V2/


# =============================================================================
# CHECKS INDIVIDUALES
# =============================================================================

def check_config():
    """
    Verifica que config.json existe y es parseable.
    Returns: (ok: bool, message: str)
    """
    config_path = SCRIPT_DIR / "config.json"
    if not config_path.exists():
        return False, f"config.json no encontrado en: {config_path}"
    
    try:
        import json
        json.loads(config_path.read_text(encoding='utf-8'))
        return True, "config.json OK"
    except Exception as e:
        return False, f"config.json inválido: {e}"


def check_env_vars():
    """
    Verifica variables de entorno críticas.
    Lee de config.json qué ENVs necesita.
    Returns: (ok: bool, message: str)
    """
    try:
        from .config import get_env_status
        status = get_env_status()
    except Exception as e:
        return False, f"No pude verificar env vars: {e}"
    
    if status['missing']:
        missing_str = ', '.join(status['missing'])
        return False, f"Variables de entorno faltantes: {missing_str}"
    
    resolved_count = len(status['resolved'])
    return True, f"Env vars OK ({resolved_count} resueltas)"


def check_database():
    """
    Verifica que SQLite DB existe (o la crea).
    Returns: (ok: bool, message: str)
    """
    db_path = SCRIPT_DIR / "meme_reaction.db"
    
    try:
        from .db import init_db
        init_db()
        return True, f"Database OK: {db_path.name}"
    except Exception as e:
        return False, f"Error inicializando DB: {e}"


def check_brave():
    """
    Verifica que Brave Browser existe en el path configurado.
    Solo relevante para scripts de scraping.
    Returns: (ok: bool, message: str)
    """
    try:
        from .config import get_section
        brave_path = get_section('scraping').get('brave_path', '')
    except Exception:
        brave_path = r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
    
    if not brave_path:
        return True, "Brave path no configurado (OK si no es script de scraping)"
    
    if Path(brave_path).exists():
        return True, f"Brave encontrado: {Path(brave_path).name}"
    
    return False, f"Brave NO encontrado en: {brave_path}"


def check_ffmpeg():
    """
    Verifica que ffmpeg está accesible en PATH.
    Solo relevante para descarga de videos.
    Returns: (ok: bool, message: str)
    """
    ffmpeg_path = shutil.which('ffmpeg')
    if ffmpeg_path:
        return True, f"ffmpeg OK: {ffmpeg_path}"
    return False, "ffmpeg NO encontrado en PATH"


def check_openai_key():
    """
    Verifica que OPENAI_API_KEY existe y parece válida.
    Returns: (ok: bool, message: str)
    """
    key = os.environ.get('OPENAI_API_KEY', '')
    if not key:
        return False, "OPENAI_API_KEY no está en variables de entorno"
    if not key.startswith('sk-'):
        return False, "OPENAI_API_KEY no parece válida (no empieza con 'sk-')"
    return True, f"OPENAI_API_KEY OK (sk-...{key[-4:]})"


def check_directories():
    """
    Verifica/crea directorios necesarios.
    Returns: (ok: bool, message: str)
    """
    dirs = [
        SCRIPT_DIR / "memes_descargados",
        SCRIPT_DIR / "clips",
        SCRIPT_DIR / "output",
        SCRIPT_DIR / "logs",
    ]
    
    created = []
    for d in dirs:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d.name)
    
    if created:
        return True, f"Directorios creados: {', '.join(created)}"
    return True, "Directorios OK"


def check_temp_cleanup():
    """
    Limpia archivos temporales huérfanos.
    Returns: (ok: bool, message: str)
    """
    temp_dirs = [
        SCRIPT_DIR / "_temp_video",
        SCRIPT_DIR / "_temp",
    ]
    
    cleaned = 0
    for d in temp_dirs:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            cleaned += 1
    
    if cleaned:
        return True, f"Limpiados {cleaned} directorios temporales"
    return True, "Sin temporales pendientes"


# =============================================================================
# RUNNER PRINCIPAL
# =============================================================================

# Todos los checks disponibles
ALL_CHECKS = {
    'config': check_config,
    'env': check_env_vars,
    'db': check_database,
    'brave': check_brave,
    'ffmpeg': check_ffmpeg,
    'openai': check_openai_key,
    'dirs': check_directories,
    'cleanup': check_temp_cleanup,
}

# Checks críticos (si fallan, exit)
CRITICAL_CHECKS = {'config', 'db'}

# Checks por defecto (si no se especifican)
DEFAULT_CHECKS = ['config', 'env', 'db', 'dirs', 'cleanup']


def run_health_checks(checks=None, exit_on_critical=True, verbose=True):
    """
    Ejecuta health checks.
    
    Args:
        checks: Lista de checks a ejecutar (default: DEFAULT_CHECKS)
        exit_on_critical: Si True, exit(1) si un check crítico falla
        verbose: Si True, imprime resultados
    
    Returns:
        dict: {check_name: (ok, message)}
    """
    if checks is None:
        checks = DEFAULT_CHECKS
    
    results = {}
    has_critical_failure = False
    
    if verbose:
        print("")
        print("=" * 50)
        print("   HEALTH CHECKS")
        print("=" * 50)
    
    for check_name in checks:
        if check_name not in ALL_CHECKS:
            if verbose:
                print(f"   [?] Check desconocido: {check_name}")
            continue
        
        try:
            ok, message = ALL_CHECKS[check_name]()
        except Exception as e:
            ok, message = False, f"Exception: {e}"
        
        results[check_name] = (ok, message)
        
        if verbose:
            icon = "✅" if ok else "❌"
            critical_tag = " [CRITICO]" if check_name in CRITICAL_CHECKS and not ok else ""
            print(f"   {icon} {check_name}: {message}{critical_tag}")
        
        if not ok and check_name in CRITICAL_CHECKS:
            has_critical_failure = True
    
    if verbose:
        print("=" * 50)
    
    if has_critical_failure and exit_on_critical:
        print("\n   [X] ABORTANDO: Health check crítico falló.")
        print("       Corrige el problema antes de ejecutar el pipeline.")
        sys.exit(1)
    
    return results
