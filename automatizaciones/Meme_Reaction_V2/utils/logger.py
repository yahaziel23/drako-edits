#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Logger Module

Logging estructurado con archivo rotativo.
Reemplaza todos los print() del pipeline.

Uso:
    from utils.logger import setup_logger, get_logger
    
    # Setup (una vez al inicio del script)
    setup_logger('1b_scrape_nuevos')
    
    # Usar en cualquier parte
    log = get_logger()
    log.info("Scrapeando perfil: elmello2023")
    log.warning("Sin posts nuevos")
    log.error("Rate limit alcanzado", exc_info=True)
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent  # Meme_Reaction_V2/
LOGS_DIR = SCRIPT_DIR / "logs"

# Singleton logger
_logger = None
_metrics = {}


# =============================================================================
# FORMATO CUSTOM
# =============================================================================

class ColorFormatter(logging.Formatter):
    """
    Formatter con colores para terminal (solo stdout).
    Los archivos de log NO tienen colores.
    """
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[41m',  # Red background
    }
    RESET = '\033[0m'

    def format(self, record):
        color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


# =============================================================================
# SETUP
# =============================================================================

def setup_logger(script_name, level=None):
    """
    Configura el logger para un script específico.
    Crea archivo de log rotativo + output a terminal con colores.
    
    Args:
        script_name: Nombre del script (sin .py) - se usa en el filename
        level: Override del nivel (default: lee de config.json)
    """
    global _logger, _metrics
    
    # Determinar nivel
    if level is None:
        try:
            from .config import get_config
            cfg = get_config()
            level = cfg.get('logging', {}).get('level', 'INFO')
        except Exception:
            level = 'INFO'
    
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Crear directorio de logs
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Nombre del archivo: {script}_{fecha}.log
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = LOGS_DIR / f"{script_name}_{timestamp}.log"
    
    # Configurar logger
    _logger = logging.getLogger('meme_reaction')
    _logger.setLevel(log_level)
    _logger.handlers.clear()  # Evita duplicados en re-setup
    
    # Handler: Archivo (rotativo, sin colores)
    try:
        from .config import get_config
        cfg = get_config()
        max_bytes = cfg.get('logging', {}).get('file_rotation_mb', 5) * 1024 * 1024
    except Exception:
        max_bytes = 5 * 1024 * 1024  # 5MB default
    
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=5, encoding='utf-8'
    )
    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    _logger.addHandler(file_handler)
    
    # Handler: Terminal (con colores)
    console_handler = logging.StreamHandler(sys.stdout)
    console_format = ColorFormatter(
        '%(levelname)-8s | %(message)s'
    )
    console_handler.setFormatter(console_format)
    _logger.addHandler(console_handler)
    
    # Inicializar métricas de sesión
    _metrics = {
        'script': script_name,
        'started_at': datetime.now(),
        'tokens_used': 0,
        'items_processed': 0,
        'items_skipped': 0,
        'items_error': 0,
        'api_calls': 0,
    }
    
    _logger.info(f"=== {script_name.upper()} - INICIO ===")
    _logger.info(f"Log file: {log_file.name}")
    
    return _logger


def get_logger():
    """
    Obtiene el logger configurado.
    Si no se hizo setup, crea uno básico.
    """
    global _logger
    if _logger is None:
        _logger = logging.getLogger('meme_reaction')
        if not _logger.handlers:
            # Fallback: solo terminal
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter('%(levelname)-8s | %(message)s'))
            _logger.addHandler(handler)
            _logger.setLevel(logging.INFO)
    return _logger


# =============================================================================
# METRICAS DE SESION
# =============================================================================

def track_tokens(tokens):
    """Agrega tokens usados al conteo de sesión."""
    _metrics['tokens_used'] = _metrics.get('tokens_used', 0) + tokens


def track_item(result='processed'):
    """
    Incrementa conteo de items.
    result: 'processed' | 'skipped' | 'error'
    """
    key = f'items_{result}'
    _metrics[key] = _metrics.get(key, 0) + 1


def track_api_call():
    """Incrementa conteo de llamadas a API."""
    _metrics['api_calls'] = _metrics.get('api_calls', 0) + 1


def get_metrics():
    """Retorna métricas de la sesión actual."""
    metrics = _metrics.copy()
    if 'started_at' in metrics:
        elapsed = (datetime.now() - metrics['started_at']).total_seconds()
        metrics['duration_s'] = round(elapsed, 2)
    return metrics


def log_summary():
    """
    Imprime resumen de la sesión al final del script.
    Llamar antes de exit.
    """
    log = get_logger()
    m = get_metrics()
    
    log.info("")
    log.info(f"=== {m.get('script', '?').upper()} - RESUMEN ===")
    log.info(f"   Duración:        {m.get('duration_s', '?')}s")
    log.info(f"   Procesados:      {m.get('items_processed', 0)}")
    log.info(f"   Skipped:         {m.get('items_skipped', 0)}")
    log.info(f"   Errores:         {m.get('items_error', 0)}")
    log.info(f"   API calls:       {m.get('api_calls', 0)}")
    log.info(f"   Tokens usados:   {m.get('tokens_used', 0)}")
    log.info("="*50)
    
    return m


# =============================================================================
# CLEANUP
# =============================================================================

def cleanup_old_logs(keep_days=None):
    """
    Elimina logs más antiguos que keep_days.
    Default: lee de config.json.
    """
    if keep_days is None:
        try:
            from .config import get_config
            cfg = get_config()
            keep_days = cfg.get('logging', {}).get('keep_logs_days', 30)
        except Exception:
            keep_days = 30
    
    if not LOGS_DIR.exists():
        return 0
    
    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    removed = 0
    for f in LOGS_DIR.glob('*.log*'):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed
