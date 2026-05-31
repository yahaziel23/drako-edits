#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Status (Resumen del Pipeline)

Muestra el estado completo del pipeline en un vistazo.
Lee de SQLite y presenta conteos por cada cola/status.

Uso:
    python status.py              # Resumen rápido
    python status.py --detailed   # Desglose por perfil
    python status.py --telegram   # Envía resumen por Telegram
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Setup path para imports locales
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import get_db, init_db
from utils.rate_limiter import RateLimiter


# =============================================================================
# QUERIES
# =============================================================================

def get_status_counts(db):
    """
    Obtiene conteos agrupados por status de la tabla memes.
    Returns: dict {status: count}
    """
    rows = db.execute(
        "SELECT status, COUNT(*) as cnt FROM memes GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    return {row['status']: row['cnt'] for row in rows}


def get_source_type_counts(db):
    """
    Conteos por source_type (foto vs frame).
    Returns: dict {source_type: count}
    """
    rows = db.execute(
        "SELECT source_type, COUNT(*) as cnt FROM memes GROUP BY source_type"
    ).fetchall()
    return {row['source_type']: row['cnt'] for row in rows}


def get_profile_counts(db):
    """
    Conteos por perfil de origen.
    Returns: dict {profile: count}
    """
    rows = db.execute(
        "SELECT source_profile, COUNT(*) as cnt FROM memes GROUP BY source_profile ORDER BY cnt DESC"
    ).fetchall()
    return {row['source_profile']: row['cnt'] for row in rows}


def get_match_stats(db):
    """
    Estadísticas de matches.
    Returns: dict con conteos por status de match
    """
    rows = db.execute(
        "SELECT status, match_type, COUNT(*) as cnt FROM matches GROUP BY status, match_type"
    ).fetchall()
    stats = {}
    for row in rows:
        key = f"{row['status']}_{row['match_type']}"
        stats[key] = row['cnt']
    return stats


def get_videos_count(db):
    """Cuenta videos generados."""
    row = db.execute("SELECT COUNT(*) as cnt FROM videos_generados").fetchone()
    return row['cnt'] if row else 0


def get_uploads_count(db):
    """Cuenta uploads exitosos."""
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM uploads WHERE status = 'subido'"
    ).fetchone()
    return row['cnt'] if row else 0


def get_clips_count(db):
    """Cuenta clips en catálogo."""
    row = db.execute("SELECT COUNT(*) as cnt FROM clips").fetchone()
    return row['cnt'] if row else 0


def get_today_activity(db):
    """
    Actividad del día (posts procesados hoy).
    """
    today = datetime.now().strftime('%Y-%m-%d')
    
    scraped = db.execute(
        "SELECT COUNT(*) as cnt FROM memes WHERE date(scraped_at) = ?", (today,)
    ).fetchone()['cnt']
    
    classified = db.execute(
        "SELECT COUNT(*) as cnt FROM clasificaciones WHERE date(classified_at) = ?", (today,)
    ).fetchone()['cnt']
    
    generated = db.execute(
        "SELECT COUNT(*) as cnt FROM videos_generados WHERE date(generated_at) = ?", (today,)
    ).fetchone()['cnt']
    
    return {'scraped': scraped, 'classified': classified, 'generated': generated}


# =============================================================================
# DISPLAY
# =============================================================================

SEP = "=" * 60


def display_status(detailed=False):
    """Muestra el status completo del pipeline."""
    db = init_db()
    
    counts = get_status_counts(db)
    source_types = get_source_type_counts(db)
    today = get_today_activity(db)
    clips_count = get_clips_count(db)
    videos_count = get_videos_count(db)
    uploads_count = get_uploads_count(db)
    total_memes = sum(counts.values())
    
    print(f"\n{SEP}")
    print(f"   MEME REACTION V2 - STATUS")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(SEP)
    
    # Totales
    print(f"   Total memes en DB:   {total_memes}")
    print(f"   Clips catalogados:   {clips_count}")
    print(f"   Videos generados:    {videos_count}")
    print(f"   Subidos a redes:     {uploads_count}")
    print(f"   {'─' * 40}")
    
    # Pipeline status
    print(f"")
    print(f"   📥 Por descargar:         {counts.get('por_descargar', 0)}")
    print(f"   🖼️  Descargados (foto):     {source_types.get('foto', 0)}")
    print(f"   🎥 Descargados (frame):    {source_types.get('frame', 0)}")
    print(f"")
    print(f"   👁️  Pendientes review:      {counts.get('pendiente_review', 0)}")
    print(f"   ✅ Listos clasificar:     {counts.get('listo_clasificar', 0)}")
    print(f"   🧠 Clasificados:           {counts.get('clasificado', 0)}")
    print(f"")
    print(f"   🎬 Pendiente match:        {counts.get('pendiente_match', 0)}")
    print(f"   🎬 Matched (auto):         {counts.get('matched_auto', 0)}")
    print(f"   🎬 Match review (cola):    {counts.get('match_review', 0)}")
    print(f"   🎬 Buscar clip:            {counts.get('buscar_clip', 0)}")
    print(f"")
    print(f"   🎥 Por generar video:      {counts.get('por_generar', 0)}")
    print(f"   🎥 Generados:              {counts.get('generado', 0)}")
    print(f"   📤 Por subir:              {counts.get('por_subir', 0)}")
    print(f"   📤 Subidos:                {counts.get('subido', 0)}")
    print(f"")
    
    # Terminal states
    rechazados = counts.get('rechazado', 0)
    descartados = counts.get('descartado_ia', 0)
    if rechazados or descartados:
        print(f"   🚫 Rechazados (manual):    {rechazados}")
        print(f"   🚫 Descartados (IA):       {descartados}")
        print(f"")
    
    # Actividad de hoy
    print(f"   {'─' * 40}")
    print(f"   Hoy: +{today['scraped']} scrapeados, "
          f"+{today['classified']} clasificados, "
          f"+{today['generated']} generados")
    
    # Rate limits
    print(f"")
    print(f"   {'─' * 40}")
    print(f"   API Budget:")
    for api in ['openai', 'instagram']:
        limiter = RateLimiter(api)
        print(f"     {limiter.get_summary()}")
    
    print(SEP)
    
    # Detailed: por perfil
    if detailed:
        profiles = get_profile_counts(db)
        print(f"\n   DESGLOSE POR PERFIL:")
        print(f"   {'─' * 40}")
        for profile, count in profiles.items():
            print(f"   @{profile}: {count} posts")
        print(f"")
    
    return counts


def get_status_text():
    """
    Genera texto del status (para Telegram).
    Versión sin emojis fancy, plain text.
    """
    db = init_db()
    counts = get_status_counts(db)
    today = get_today_activity(db)
    total = sum(counts.values())
    
    lines = [
        f"Total: {total} memes",
        f"",
        f"Por descargar: {counts.get('por_descargar', 0)}",
        f"Pendientes review: {counts.get('pendiente_review', 0)}",
        f"Listos clasificar: {counts.get('listo_clasificar', 0)}",
        f"Pendiente match: {counts.get('pendiente_match', 0)}",
        f"Por generar: {counts.get('por_generar', 0)}",
        f"Por subir: {counts.get('por_subir', 0)}",
        f"",
        f"Hoy: +{today['scraped']} scrape, +{today['classified']} classify, +{today['generated']} gen",
    ]
    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Meme Reaction V2 - Status")
    parser.add_argument('--detailed', '-d', action='store_true',
                        help="Muestra desglose por perfil")
    parser.add_argument('--telegram', '-t', action='store_true',
                        help="Envía resumen por Telegram")
    args = parser.parse_args()
    
    display_status(detailed=args.detailed)
    
    if args.telegram:
        from utils.telegram import send_notification
        text = get_status_text()
        success = send_notification(f"📊 *Status*\n```\n{text}\n```")
        if success:
            print("\n   [✓] Resumen enviado por Telegram")
        else:
            print("\n   [!] No se pudo enviar por Telegram")


if __name__ == "__main__":
    main()
