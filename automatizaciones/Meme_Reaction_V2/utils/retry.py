#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Retry Module

Decorator para reintentos con backoff exponencial.
Configurable por tipo de error y con hooks específicos para OpenAI/IG.

Uso:
    from utils.retry import with_retry
    
    @with_retry(max_attempts=3, backoff_factor=2)
    def call_openai(prompt):
        ...
    
    @with_retry(max_attempts=2, retry_on=(TimeoutError, ConnectionError))
    def scrape_profile(url):
        ...
"""

import time
import functools
import json
from typing import Tuple, Type, Callable, Optional


# =============================================================================
# DECORATOR
# =============================================================================

def with_retry(
    max_attempts: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    retry_on: Tuple[Type[Exception], ...] = (Exception,),
    exclude: Tuple[Type[Exception], ...] = (),
    on_retry: Optional[Callable] = None,
    logger_name: str = 'meme_reaction'
):
    """
    Decorator que reintenta una función con backoff exponencial.
    
    Args:
        max_attempts: Número máximo de intentos (incluye el primero)
        backoff_factor: Multiplicador del delay entre intentos
        initial_delay: Delay inicial en segundos
        max_delay: Delay máximo (cap)
        retry_on: Tupla de excepciones que disparan retry
        exclude: Excepciones que NUNCA se reintentan (override de retry_on)
        on_retry: Callback(attempt, exception, delay) llamado antes de cada retry
        logger_name: Nombre del logger a usar
    
    Returns:
        Decorator function
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            import logging
            log = logging.getLogger(logger_name)
            
            delay = initial_delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exclude as e:
                    # Never retry these
                    raise
                except retry_on as e:
                    last_exception = e
                    
                    if attempt == max_attempts:
                        log.error(
                            f"[RETRY] {func.__name__} falló después de "
                            f"{max_attempts} intentos. Último error: {e}"
                        )
                        raise
                    
                    # Calcular delay con cap
                    actual_delay = min(delay, max_delay)
                    
                    log.warning(
                        f"[RETRY] {func.__name__} intento {attempt}/{max_attempts} "
                        f"falló: {type(e).__name__}: {str(e)[:100]}. "
                        f"Reintentando en {actual_delay:.1f}s..."
                    )
                    
                    # Callback opcional
                    if on_retry:
                        on_retry(attempt, e, actual_delay)
                    
                    time.sleep(actual_delay)
                    delay *= backoff_factor
            
            # Shouldn't reach here, but just in case
            raise last_exception
        
        return wrapper
    return decorator


# =============================================================================
# PRESETS PARA CASOS COMUNES
# =============================================================================

def retry_openai(func):
    """
    Preset para llamadas a OpenAI.
    Reintenta en: rate limit, timeout, bad gateway, JSON inválido.
    NO reintenta en: auth error, invalid request.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import logging
        log = logging.getLogger('meme_reaction')
        
        max_attempts = 3
        delay = 2.0
        
        for attempt in range(1, max_attempts + 1):
            try:
                result = func(*args, **kwargs)
                
                # Validar que el resultado sea JSON parseable (si es string)
                if isinstance(result, str):
                    try:
                        json.loads(result)
                    except json.JSONDecodeError:
                        if attempt < max_attempts:
                            log.warning(
                                f"[RETRY-OPENAI] Respuesta no es JSON válido. "
                                f"Reintentando ({attempt}/{max_attempts})..."
                            )
                            time.sleep(delay)
                            delay *= 2
                            continue
                        else:
                            log.error("[RETRY-OPENAI] JSON inválido tras todos los intentos")
                
                return result
                
            except Exception as e:
                error_str = str(e).lower()
                
                # No reintentar errores de auth/request
                if any(x in error_str for x in ['auth', '401', 'invalid_api_key', '403']):
                    raise
                
                # Reintentar rate limit, timeout, server errors
                if attempt < max_attempts and any(
                    x in error_str for x in ['429', 'rate', 'timeout', '500', '502', '503', 'connection']
                ):
                    wait = delay if '429' not in error_str else delay * 5  # Rate limit = espera larga
                    log.warning(
                        f"[RETRY-OPENAI] {type(e).__name__}: {str(e)[:80]}. "
                        f"Esperando {wait:.0f}s... ({attempt}/{max_attempts})"
                    )
                    time.sleep(wait)
                    delay *= 2
                    continue
                
                raise
        
        # Fallback
        return func(*args, **kwargs)
    
    return wrapper


def retry_instagram(func):
    """
    Preset para requests a Instagram (instaloader/selenium).
    Reintenta en: timeout, connection error, 429.
    Auto-stop en: login required, 403 persistente.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import logging
        log = logging.getLogger('meme_reaction')
        
        max_attempts = 2  # IG es más conservador
        delay = 5.0
        
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_str = str(e).lower()
                
                # STOP total - no reintentar
                if any(x in error_str for x in ['login', 'redirect', 'challenge']):
                    log.error(f"[IG-STOP] Posible ban/login required: {e}")
                    raise
                
                # Retry en timeout/connection
                if attempt < max_attempts and any(
                    x in error_str for x in ['timeout', 'connection', '429', '503']
                ):
                    log.warning(
                        f"[RETRY-IG] {type(e).__name__}. "
                        f"Esperando {delay:.0f}s... ({attempt}/{max_attempts})"
                    )
                    time.sleep(delay)
                    delay *= 3  # Más conservador con IG
                    continue
                
                raise
    
    return wrapper
