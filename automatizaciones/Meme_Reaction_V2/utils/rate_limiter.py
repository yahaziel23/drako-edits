#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Rate Limiter Module

Budget tracking de API usage. Previene exceder límites antes de que
la API te banee.

Uso:
    from utils.rate_limiter import RateLimiter
    
    limiter = RateLimiter('openai')
    
    if limiter.can_request():
        # ... hacer request ...
        limiter.log_request(tokens=150)
    else:
        print("Budget agotado por hoy")
"""

from datetime import datetime
from pathlib import Path


# =============================================================================
# RATE LIMITER CLASS
# =============================================================================

class RateLimiter:
    """
    Controla el budget de requests a una API específica.
    Lee límites de config.json y trackea uso en SQLite.
    """
    
    def __init__(self, api_name):
        """
        Args:
            api_name: 'openai' | 'instagram' | 'telegram'
        """
        self.api = api_name
        self._limits = None
    
    @property
    def limits(self):
        """Carga límites de config.json (lazy)."""
        if self._limits is None:
            try:
                from .config import get_config
                cfg = get_config()
                self._limits = cfg.get('rate_limits', {}).get(self.api, {})
            except Exception:
                self._limits = {}
        return self._limits
    
    def get_usage(self):
        """
        Obtiene uso del día actual desde SQLite.
        Returns: {'requests': int, 'tokens': int}
        """
        from .db import get_daily_usage
        return get_daily_usage(self.api)
    
    def can_request(self, tokens_estimate=0):
        """
        Verifica si queda budget para un request más.
        
        Args:
            tokens_estimate: Tokens estimados que usará este request
        
        Returns:
            bool: True si hay budget disponible
        """
        usage = self.get_usage()
        max_requests = self.limits.get('max_requests_per_day', float('inf'))
        max_tokens = self.limits.get('max_tokens_per_day', float('inf'))
        
        if usage['requests'] >= max_requests:
            return False
        if tokens_estimate and (usage['tokens'] + tokens_estimate) > max_tokens:
            return False
        
        return True
    
    def is_warning(self):
        """
        Verifica si estamos cerca del límite (warning threshold).
        Returns: (bool, str message)
        """
        usage = self.get_usage()
        threshold = self.limits.get('warning_threshold', 0.8)
        max_requests = self.limits.get('max_requests_per_day', float('inf'))
        max_tokens = self.limits.get('max_tokens_per_day', float('inf'))
        
        messages = []
        
        if max_requests != float('inf'):
            ratio = usage['requests'] / max_requests
            if ratio >= threshold:
                messages.append(
                    f"Requests: {usage['requests']}/{max_requests} ({ratio:.0%})"
                )
        
        if max_tokens != float('inf'):
            ratio = usage['tokens'] / max_tokens
            if ratio >= threshold:
                messages.append(
                    f"Tokens: {usage['tokens']}/{max_tokens} ({ratio:.0%})"
                )
        
        if messages:
            return True, f"[WARNING] {self.api}: {'; '.join(messages)}"
        return False, ""
    
    def log_request(self, tokens=0):
        """
        Registra un request realizado.
        También imprime warning si estamos cerca del límite.
        
        Args:
            tokens: Tokens consumidos en este request
        """
        from .db import log_api_request
        log_api_request(self.api, tokens)
        
        # Check warning
        is_warn, msg = self.is_warning()
        if is_warn:
            import logging
            log = logging.getLogger('meme_reaction')
            log.warning(msg)
    
    def get_remaining(self):
        """
        Retorna budget restante del día.
        Returns: {'requests': int, 'tokens': int}
        """
        usage = self.get_usage()
        max_requests = self.limits.get('max_requests_per_day', float('inf'))
        max_tokens = self.limits.get('max_tokens_per_day', float('inf'))
        
        return {
            'requests': max(0, max_requests - usage['requests']) if max_requests != float('inf') else -1,
            'tokens': max(0, max_tokens - usage['tokens']) if max_tokens != float('inf') else -1,
        }
    
    def get_summary(self):
        """
        Resumen legible del estado de la API.
        Para status.py.
        """
        usage = self.get_usage()
        remaining = self.get_remaining()
        max_req = self.limits.get('max_requests_per_day', '\u221e')
        max_tok = self.limits.get('max_tokens_per_day', '\u221e')
        
        return (
            f"{self.api}: "
            f"{usage['requests']}/{max_req} requests, "
            f"{usage['tokens']}/{max_tok} tokens "
            f"(quedan: {remaining['requests']} req, {remaining['tokens']} tok)"
        )
