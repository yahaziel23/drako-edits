#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Config Module

Carga config.json y resuelve valores que apuntan a variables de entorno.
Patrón "ENV:VAR_NAME" en config.json se reemplaza por os.environ["VAR_NAME"].

Uso:
    from utils.config import load_config, get_config
    
    config = load_config()       # Carga y cachea
    config = get_config()        # Obtiene cache (debe haberse cargado antes)
    
    # Acceso directo:
    config['clasificacion']['modelo']   # "gpt-4o"
    config['match']['auto_accept_threshold']  # 90
"""

import json
import os
from pathlib import Path
from copy import deepcopy

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent  # Meme_Reaction_V2/
CONFIG_PATH = SCRIPT_DIR / "config.json"

# Cache global
_config = None


# =============================================================================
# FUNCIONES
# =============================================================================

def _resolve_env_values(obj):
    """
    Recursivamente resuelve valores "ENV:VAR_NAME" a os.environ["VAR_NAME"].
    Si la variable no existe, deja el string original (para health check).
    """
    if isinstance(obj, dict):
        return {k: _resolve_env_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_values(item) for item in obj]
    elif isinstance(obj, str) and obj.startswith("ENV:"):
        env_var = obj[4:]  # Remove "ENV:" prefix
        return os.environ.get(env_var, obj)  # Fallback to original if not set
    return obj


def load_config(config_path=None):
    """
    Carga config.json, resuelve variables de entorno, y cachea.
    
    Args:
        config_path: Path al config.json (default: raíz del proyecto)
    
    Returns:
        dict con toda la configuración
    
    Raises:
        FileNotFoundError: si no existe config.json
        json.JSONDecodeError: si el JSON es inválido
    """
    global _config
    
    path = Path(config_path) if config_path else CONFIG_PATH
    
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontró config.json en: {path}\n"
            f"Crea uno basado en la documentación del proyecto."
        )
    
    raw = json.loads(path.read_text(encoding='utf-8'))
    _config = _resolve_env_values(raw)
    return _config


def get_config():
    """
    Obtiene la config cacheada. Carga automáticamente si no se ha hecho.
    
    Returns:
        dict con la configuración
    """
    global _config
    if _config is None:
        return load_config()
    return _config


def get_section(section_name):
    """
    Atajo para obtener una sección específica.
    
    Uso:
        scraping_cfg = get_section('scraping')
        scraping_cfg['scroll_count_inicial']  # 20
    """
    config = get_config()
    if section_name not in config:
        raise KeyError(
            f"Sección '{section_name}' no existe en config.json. "
            f"Secciones disponibles: {list(config.keys())}"
        )
    return config[section_name]


def is_dry_run():
    """Retorna True si está en modo dry_run."""
    return get_config().get('dry_run', False)


def get_env_status():
    """
    Revisa qué variables de entorno están configuradas y cuáles faltan.
    Útil para health checks.
    
    Returns:
        dict: {'resolved': [...], 'missing': [...]}
    """
    path = CONFIG_PATH
    if not path.exists():
        return {'resolved': [], 'missing': ['config.json NOT FOUND']}
    
    raw = json.loads(path.read_text(encoding='utf-8'))
    resolved = []
    missing = []
    
    def _scan(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                _scan(v)
        elif isinstance(obj, list):
            for item in obj:
                _scan(item)
        elif isinstance(obj, str) and obj.startswith("ENV:"):
            env_var = obj[4:]
            if env_var in os.environ:
                resolved.append(env_var)
            else:
                missing.append(env_var)
    
    _scan(raw)
    return {'resolved': resolved, 'missing': missing}
