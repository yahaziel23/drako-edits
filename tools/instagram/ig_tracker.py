#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Instagram Usage Tracker

Modulo compartido para trackear el uso diario de la API de Instagram.
Guarda historial en ig_usage_log.json con:
  - Uso por dia
  - Uso por metodo (nologin / login)
  - Uso por cuenta (si aplica)
  - Warm-up progresivo
  - Historial de posts descargados

Limites:
  Sin login:  Dia1=20, Dia2=40, Dia3=60, Dia4+=100
  Con login:  Dia1=50, Dia2=100, Dia3=200, Dia4+=300
"""

import json
from pathlib import Path
from datetime import date, datetime

# =============================================================================
# CONFIGURACION
# =============================================================================

TRACKER_DIR = Path(__file__).parent
LOG_FILE = TRACKER_DIR / "ig_usage_log.json"

# Warm-up schedules por metodo
WARMUP = {
    "nologin": {1: 20, 2: 40, 3: 60, "default": 100},
    "login":   {1: 50, 2: 100, 3: 200, "default": 300},
}


# =============================================================================
# FUNCIONES INTERNAS
# =============================================================================

def _load_log():
    """Carga el log de uso."""
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_log(log):
    """Guarda el log de uso."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_start_date(log, method):
    """Obtiene la fecha de inicio del warm-up para un metodo."""
    key = f"start_date_{method}"
    if key not in log:
        log[key] = str(date.today())
        _save_log(log)
    return date.fromisoformat(log[key])


def _get_day_number(log, method):
    """En que dia del warm-up estamos para este metodo."""
    start = _get_start_date(log, method)
    return (date.today() - start).days + 1


# =============================================================================
# FUNCIONES PUBLICAS
# =============================================================================

def get_daily_limit(method="nologin"):
    """
    Obtiene el limite de hoy segun warm-up.
    method: "nologin" o "login"
    """
    log = _load_log()
    day = _get_day_number(log, method)
    schedule = WARMUP.get(method, WARMUP["nologin"])
    return schedule.get(day, schedule["default"])


def get_today_usage(method="nologin", account=None):
    """
    Cuantos requests se han usado hoy para este metodo/cuenta.
    """
    log = _load_log()
    today_str = str(date.today())

    if "days" not in log:
        return 0

    day_data = log["days"].get(today_str, {})

    if account:
        key = f"login_{account}"
    else:
        key = method

    return day_data.get(key, {}).get("count", 0)


def get_remaining(method="nologin", account=None):
    """Cuantos requests quedan hoy."""
    limit = get_daily_limit(method)
    used = get_today_usage(method, account)
    return max(0, limit - used)


def log_request(method="nologin", account=None, shortcode="", media_type="", username=""):
    """
    Registra un request/descarga en el log.
    """
    log = _load_log()
    today_str = str(date.today())

    if "days" not in log:
        log["days"] = {}
    if today_str not in log["days"]:
        log["days"][today_str] = {}

    # Key segun metodo
    if account:
        key = f"login_{account}"
    else:
        key = method

    if key not in log["days"][today_str]:
        log["days"][today_str][key] = {"count": 0, "downloads": []}

    log["days"][today_str][key]["count"] += 1
    log["days"][today_str][key]["downloads"].append({
        "shortcode": shortcode,
        "type": media_type,
        "from": username,
        "time": datetime.now().strftime("%H:%M:%S"),
    })

    _save_log(log)


def show_status(method="nologin", account=None):
    """
    Muestra estado completo de limites. Retorna remaining.
    """
    log = _load_log()
    day = _get_day_number(log, method)
    limit = get_daily_limit(method)
    used = get_today_usage(method, account)
    remaining = max(0, limit - used)

    print(f"\n   {'='*50}")
    print(f"   ESTADO - Instagram ({method}{'/' + account if account else ''})")
    print(f"   {'='*50}")
    print(f"   Fecha:          {date.today()}")
    print(f"   Dia warm-up:    {day}")
    print(f"   Limite hoy:     {limit}")
    print(f"   Usados hoy:     {used}")
    print(f"   RESTANTES:      {remaining}")

    if day <= 3:
        schedule = WARMUP.get(method, WARMUP["nologin"])
        next_limit = schedule.get(day + 1, schedule["default"])
        print(f"   Manana:         {next_limit} (warm-up dia {day+1})")

    print(f"   {'='*50}")

    if remaining <= 5 and remaining > 0:
        print(f"   [!] ATENCION: Quedan muy pocos requests.")
    elif remaining <= 0:
        print(f"   [X] LIMITE ALCANZADO. Espera a manana.")

    return remaining


def check_can_download(method="nologin", account=None, count=1):
    """
    Verifica si se puede descargar 'count' posts.
    Muestra advertencia. Retorna True/False.
    """
    limit = get_daily_limit(method)
    used = get_today_usage(method, account)
    remaining = limit - used

    day = _load_log()
    day_num = _get_day_number(day, method)

    print(f"\n   [LIMITE] Dia {day_num} | Hoy: {used}/{limit} usados | Restantes: {remaining}")

    if remaining <= 0:
        print(f"   [X] LIMITE ALCANZADO. No puedes descargar hoy.")
        schedule = WARMUP.get(method, WARMUP["nologin"])
        next_limit = schedule.get(day_num + 1, schedule["default"])
        print(f"       Manana tendras: {next_limit} requests.")
        return False

    if count > remaining:
        print(f"   [!] Quieres descargar {count} pero solo quedan {remaining}.")
        print(f"       Se descargaran maximo {remaining}.")
        return True  # Puede descargar pero limitado

    if remaining <= 10:
        print(f"   [!] Quedan pocos ({remaining}). Usa con cuidado.")

    return True


def get_history_summary():
    """Muestra resumen historico de uso."""
    log = _load_log()
    if "days" not in log or not log["days"]:
        print("   No hay historial de uso.")
        return

    print(f"\n   HISTORIAL DE USO:")
    print(f"   {'Fecha':<12} {'Metodo':<15} {'Count':<8}")
    print(f"   {'-'*35}")

    days_sorted = sorted(log["days"].keys(), reverse=True)[:7]  # Ultimos 7 dias
    for d in days_sorted:
        for method_key, data in log["days"][d].items():
            count = data.get("count", 0)
            print(f"   {d:<12} {method_key:<15} {count:<8}")
