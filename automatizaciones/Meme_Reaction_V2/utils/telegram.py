#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Telegram Notifications Module

Envía notificaciones via Telegram Bot API.
Requiere: TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env

Setup (una vez):
1. Habla con @BotFather en Telegram, crea un bot, copia el token
2. Obtén tu chat_id hablando con @userinfobot
3. Agrega a .env:
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=987654321

Uso:
    from utils.telegram import send_notification, notify_video, notify_error
    
    send_notification("🎥 Video generado: meme_ABC123.mp4")
    notify_video("ABC123", "/path/to/video.mp4")
    notify_error("3_classify", "Rate limit excedido")
"""

import requests
import logging
from pathlib import Path

log = logging.getLogger('meme_reaction')


# =============================================================================
# CORE
# =============================================================================

def _get_telegram_config():
    """
    Obtiene token y chat_id de la config.
    Returns: (bot_token, chat_id, enabled) o (None, None, False)
    """
    try:
        from .config import get_section
        cfg = get_section('telegram')
    except Exception:
        return None, None, False
    
    if not cfg.get('enabled', False):
        return None, None, False
    
    bot_token = cfg.get('bot_token', '')
    chat_id = cfg.get('chat_id', '')
    
    # Si aún tiene el prefijo ENV: es que no se resolvió (variable no existe)
    if not bot_token or bot_token.startswith('ENV:'):
        return None, None, False
    if not chat_id or chat_id.startswith('ENV:'):
        return None, None, False
    
    return bot_token, chat_id, True


def send_notification(message, silent=False):
    """
    Envía un mensaje de texto por Telegram.
    
    Args:
        message: Texto del mensaje (soporta Markdown)
        silent: Si True, no hace sonido en el teléfono
    
    Returns:
        bool: True si se envió exitosamente
    """
    bot_token, chat_id, enabled = _get_telegram_config()
    
    if not enabled:
        log.debug("[TG] Telegram deshabilitado, mensaje no enviado")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown',
        'disable_notification': silent,
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            log.debug(f"[TG] Mensaje enviado: {message[:50]}...")
            return True
        else:
            log.warning(f"[TG] Error {response.status_code}: {response.text[:100]}")
            return False
    except Exception as e:
        log.warning(f"[TG] Error enviando notificación: {e}")
        return False


# =============================================================================
# HELPERS DE ALTO NIVEL
# =============================================================================

def notify_video_generated(shortcode, output_path=None):
    """
    Notifica que se generó un video nuevo.
    Solo envía si 'notificar_video_generado' está activo en config.
    """
    try:
        from .config import get_section
        cfg = get_section('telegram')
        if not cfg.get('notificar_video_generado', False):
            return False
    except Exception:
        return False
    
    msg = f"🎥 *Video generado*\n`{shortcode}`"
    if output_path:
        msg += f"\nArchivo: `{Path(output_path).name}`"
    
    return send_notification(msg)


def notify_upload(shortcode, platform, url=None):
    """
    Notifica que se subió un video a una red social.
    Solo envía si 'notificar_upload' está activo en config.
    """
    try:
        from .config import get_section
        cfg = get_section('telegram')
        if not cfg.get('notificar_upload', False):
            return False
    except Exception:
        return False
    
    msg = f"📤 *Video subido*\n`{shortcode}` \u2192 {platform}"
    if url:
        msg += f"\n[Ver post]({url})"
    
    return send_notification(msg)


def notify_error(step, error_msg):
    """
    Notifica un error en el pipeline.
    Solo envía si 'notificar_errores' está activo en config.
    """
    try:
        from .config import get_section
        cfg = get_section('telegram')
        if not cfg.get('notificar_errores', False):
            return False
    except Exception:
        return False
    
    msg = f"\u26a0\ufe0f *Error en pipeline*\nPaso: `{step}`\nError: {error_msg[:200]}"
    return send_notification(msg)


def notify_status_summary(summary_text):
    """
    Envía resumen de status (para resumen diario).
    Solo envía si 'resumen_diario' está activo en config.
    """
    try:
        from .config import get_section
        cfg = get_section('telegram')
        if not cfg.get('resumen_diario', False):
            return False
    except Exception:
        return False
    
    msg = f"📊 *Resumen diario*\n\n{summary_text}"
    return send_notification(msg)
