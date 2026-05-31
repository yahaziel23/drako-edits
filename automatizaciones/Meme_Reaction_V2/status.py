#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Status (Resumen del Pipeline)

Muestra el estado completo del pipeline en un vistazo.
Lee de SQLite y presenta conteos por cada cola/status.

Uso:
    python status.py              # Resumen rapido
    python status.py --detailed   # Desglose por perfil
    python status.py --telegram   # Envia resumen por Telegram
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import get_db, init_db
from utils.rate_limiter import RateLimiter


# =============================================================================
# QUERIES
# =============================================================================

def get_status_counts(db):
    rows = db.execute(
        "SELECT status, COUNT(*) as cnt FROM memes GROUP BY status ORDER BY cnt DESC"
    ).fetchall()
    return {row['status']: row['cnt'] for row in rows}


def get_source_type_counts(db):
    rows = db.execute(
        "SELECT source_type, COUNT(*) as cnt FROM memes GROUP BY source_type"
    ).fetchall()
    return {row['source_type']: row['cnt'] for row in rows}


def get_profile_counts(db):
    rows = db.execute(
        "SELECT source_profile, COUNT(*) as cnt FROM memes GROUP BY source_profile ORDER BY cnt DESC"
    ).fetchall()
    return {row['source_profile']: row['cnt'] for row in rows}


def get_clips_stats(db):
    """Estadisticas completas de clips."""
    total = db.execute("SELECT COUNT(*) as cnt FROM clips").fetchone()['cnt']
    
    approved = 0
    categorized = 0
    try:
        approved = db.execute("SELECT COUNT(*) as cnt FROM clips WHERE COALESCE(approved, 0) = 1").fetchone()['cnt']
    except Exception:
        pass
    try:
        categorized = db.execute("SELECT COUNT(*) as cnt FROM clips WHERE categorizado_ia_at IS NOT NULL").fetchone()['cnt']
    except Exception:
        pass
    
    pending_cat = approved - categorized if approved > categorized else 0
    
    return {
        'total': total,
        'approved': approved,
        'categorized': categorized,
        'pending_categorize': pending_cat,
    }


def get_match_stats(db):
    """Estadisticas de la tabla matches."""
    stats = {'total': 0, 'confirmed': 0, 'auto': 0}
    try:
        stats['total'] = db.execute("SELECT COUNT(DISTINCT shortcode) as cnt FROM matches").fetchone()['cnt']
        stats['confirmed'] = db.execute("SELECT COUNT(DISTINCT shortcode) as cnt FROM matches WHERE match_type = 'confirmed'").fetchone()['cnt']
        stats['auto'] = db.execute("SELECT COUNT(DISTINCT shortcode) as cnt FROM matches WHERE match_type = 'auto'").fetchone()['cnt']
    except Exception:
        pass
    return stats


def get_videos_count(db):
    try:
        return db.execute("SELECT COUNT(*) as cnt FROM videos_generados").fetchone()['cnt']
    except Exception:
        return 0


def get_uploads_count(db):
    try:
        return db.execute("SELECT COUNT(*) as cnt FROM uploads WHERE status = 'subido'").fetchone()['cnt']
    except Exception:
        return 0


def get_today_activity(db):
    today = datetime.now().strftime('%Y-%m-%d')
    
    scraped = db.execute(
        "SELECT COUNT(*) as cnt FROM memes WHERE date(scraped_at) = ?", (today,)
    ).fetchone()['cnt']
    
    classified = 0
    try:
        classified = db.execute(
            "SELECT COUNT(*) as cnt FROM clasificaciones WHERE date(classified_at) = ?", (today,)
        ).fetchone()['cnt']
    except Exception:
        pass
    
    generated = 0
    try:
        generated = db.execute(
            "SELECT COUNT(*) as cnt FROM videos_generados WHERE date(generated_at) = ?", (today,)
        ).fetchone()['cnt']
    except Exception:
        pass
    
    return {'scraped': scraped, 'classified': classified, 'generated': generated}


def get_feedback_count(db):
    """Total de feedback registrado por el usuario."""
    try:
        return db.execute("SELECT COUNT(*) as cnt FROM user_feedback").fetchone()['cnt']
    except Exception:
        return 0


# =============================================================================
# DISPLAY
# =============================================================================

SEP = "=" * 60
SUB = "-" * 44


def display_status(detailed=False):
    db = init_db()
    
    counts = get_status_counts(db)
    source_types = get_source_type_counts(db)
    clips = get_clips_stats(db)
    matches = get_match_stats(db)
    today = get_today_activity(db)
    videos_count = get_videos_count(db)
    uploads_count = get_uploads_count(db)
    feedback_count = get_feedback_count(db)
    total_memes = sum(counts.values())
    
    print(f"\n{SEP}")
    print(f"   MEME REACTION V2 - STATUS")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(SEP)
    
    # Overview
    print(f"   Total memes:       {total_memes}")
    print(f"   Total clips:       {clips['total']}")
    print(f"   Videos generados:  {videos_count}")
    print(f"   Subidos a redes:   {uploads_count}")
    print(f"   Feedback entries:  {feedback_count}")
    print(f"   {SUB}")
    
    # ---- MEMES PIPELINE ----
    print(f"")
    print(f"   PIPELINE MEMES")
    print(f"   {SUB}")
    print(f"   Scrape:")
    print(f"     Por descargar:         {counts.get('por_descargar', 0)}")
    desc_foto = 0
    desc_frame = 0
    for st in ['listo_clasificar', 'pendiente_review', 'pendiente_match', 'match_review', 'buscar_clip', 'por_generar', 'generado']:
        pass  # source_types count all, not just descargados
    print(f"     Descargados (foto):    {source_types.get('foto', 0)}")
    print(f"     Descargados (frame):   {source_types.get('frame', 0)}")
    print(f"")
    print(f"   Review:")
    print(f"     Pendientes review:     {counts.get('pendiente_review', 0)}")
    print(f"     Listos clasificar:     {counts.get('listo_clasificar', 0)}")
    print(f"")
    print(f"   Clasificacion:")
    print(f"     Pendiente match:       {counts.get('pendiente_match', 0)}")
    print(f"")
    print(f"   Matching:")
    print(f"     En review (40-89%):    {counts.get('match_review', 0)}")
    print(f"     Sin clip (<40%):       {counts.get('buscar_clip', 0)}")
    print(f"     Confirmados:           {matches.get('confirmed', 0)}")
    print(f"")
    print(f"   Generacion:")
    print(f"     Por generar:           {counts.get('por_generar', 0)}")
    print(f"     Generados:             {counts.get('generado', 0)}")
    print(f"     Por subir:             {counts.get('por_subir', 0)}")
    print(f"     Subidos:               {counts.get('subido', 0)}")
    
    # Terminal
    rechazados = counts.get('rechazado', 0)
    descartados = counts.get('descartado_ia', 0)
    if rechazados or descartados:
        print(f"")
        print(f"   Descartados:")
        print(f"     Rechazados (manual):   {rechazados}")
        print(f"     Descartados (IA):      {descartados}")
    
    # ---- CLIPS PIPELINE ----
    print(f"")
    print(f"   {SUB}")
    print(f"   PIPELINE CLIPS")
    print(f"   {SUB}")
    print(f"     Total:                 {clips['total']}")
    print(f"     Aprobados:             {clips['approved']}")
    print(f"     Categorizados (IA):    {clips['categorized']}")
    print(f"     Pendientes IA:         {clips['pending_categorize']}")
    
    # ---- HOY ----
    print(f"")
    print(f"   {SUB}")
    print(f"   HOY: +{today['scraped']} scrape, +{today['classified']} clasificar, +{today['generated']} generar")
    
    # ---- API BUDGET ----
    print(f"")
    print(f"   {SUB}")
    print(f"   API Budget:")
    for api in ['openai', 'instagram']:
        try:
            limiter = RateLimiter(api)
            print(f"     {limiter.get_summary()}")
        except Exception:
            pass
    
    print(SEP)
    
    # ---- NEXT STEPS (automatic suggestions) ----
    print(f"")
    print(f"   SIGUIENTE PASO SUGERIDO:")
    suggestions = []
    # Priority: downstream actions first (unblock the pipeline)
    if counts.get('match_review', 0) > 0:
        suggestions.append(f"     python catalogo_matches.py  ({counts['match_review']} matches por revisar)")
    if counts.get('por_generar', 0) > 0:
        suggestions.append(f"     python 7_generate_video.py  ({counts['por_generar']} listos)")
    if counts.get('pendiente_match', 0) > 0:
        suggestions.append(f"     python 4_match_clip.py  ({counts['pendiente_match']} por matchear)")
    if clips['pending_categorize'] > 0:
        suggestions.append(f"     python 3b_categorizar_clips.py  ({clips['pending_categorize']} clips)")
    if counts.get('listo_clasificar', 0) > 0:
        suggestions.append(f"     python 3_classify_meme.py  ({counts['listo_clasificar']} memes)")
    if counts.get('pendiente_review', 0) > 0:
        suggestions.append(f"     python batch_review.py  ({counts['pendiente_review']} frames)")
    if counts.get('por_descargar', 0) > 0:
        suggestions.append(f"     python 2_download_memes.py  ({counts['por_descargar']} pendientes)")
    if suggestions:
        for s in suggestions[:3]:  # Top 3 priorities
            print(s)
    else:
        print(f"     Todo al dia! Scrapea mas o descarga mas clips.")
    print(f"")
    
    # Detailed
    if detailed:
        profiles = get_profile_counts(db)
        print(f"   DESGLOSE POR PERFIL:")
        print(f"   {SUB}")
        for profile, count in profiles.items():
            print(f"   @{profile}: {count} posts")
        print(f"")
    
    return counts


def get_status_text():
    db = init_db()
    counts = get_status_counts(db)
    clips = get_clips_stats(db)
    today = get_today_activity(db)
    total = sum(counts.values())
    
    lines = [
        f"Total: {total} memes | {clips['total']} clips",
        f"",
        f"Por descargar: {counts.get('por_descargar', 0)}",
        f"Pendientes review: {counts.get('pendiente_review', 0)}",
        f"Listos clasificar: {counts.get('listo_clasificar', 0)}",
        f"Pendiente match: {counts.get('pendiente_match', 0)}",
        f"Match review: {counts.get('match_review', 0)}",
        f"Por generar: {counts.get('por_generar', 0)}",
        f"Clips sin categorizar: {clips['pending_categorize']}",
        f"",
        f"Hoy: +{today['scraped']} scrape, +{today['classified']} classify, +{today['generated']} gen",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Meme Reaction V2 - Status")
    parser.add_argument('--detailed', '-d', action='store_true',
                        help="Muestra desglose por perfil")
    parser.add_argument('--telegram', '-t', action='store_true',
                        help="Envia resumen por Telegram")
    args = parser.parse_args()
    
    display_status(detailed=args.detailed)
    
    if args.telegram:
        from utils.telegram import send_notification
        text = get_status_text()
        success = send_notification(f"Status:\n{text}")
        if success:
            print("   [OK] Resumen enviado por Telegram")
        else:
            print("   [!] No se pudo enviar por Telegram")


if __name__ == "__main__":
    main()
