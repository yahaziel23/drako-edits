#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Export Feedback

Exporta clasificaciones + feedback del usuario en un formato listo
para copiar y pegar. Sirve para mejorar el prompt de clasificacion.

Uso:
    python export_feedback.py                  # Todo (clasificaciones + feedback)
    python export_feedback.py --only-feedback  # Solo los que tienen notas
    python export_feedback.py --only-rejected  # Solo descartados por usuario
    python export_feedback.py --version 1      # Solo prompt version 1
    python export_feedback.py --clipboard      # Copia al clipboard directo
    python export_feedback.py --file reporte.txt  # Guarda a archivo

El output es texto formateado listo para pegar en el chat.
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db
from utils.config import load_config


def get_all_data(version=None, only_feedback=False, only_rejected=False):
    """Obtiene clasificaciones + feedback."""
    db = get_db()
    
    # Clasificaciones
    query = """
        SELECT m.shortcode, m.source_profile, m.source_type, m.likes, m.status,
               c.valido, c.es_video_real, c.confianza, c.categorias, c.descripcion,
               c.ideas_video, c.background_color, c.dia_especial, c.prompt_version,
               c.tokens_used
        FROM memes m
        JOIN clasificaciones c ON m.shortcode = c.shortcode
    """
    params = []
    
    if version is not None:
        query += " WHERE c.prompt_version = ?"
        params.append(version)
    
    query += " ORDER BY c.confianza ASC"
    classifications = db.execute(query, params).fetchall()
    
    # Feedback
    feedback_map = {}
    try:
        feedback_rows = db.execute("""
            SELECT shortcode, step, feedback_text, timestamp
            FROM user_feedback
            ORDER BY timestamp
        """).fetchall()
        for row in feedback_rows:
            sc = row['shortcode']
            if sc not in feedback_map:
                feedback_map[sc] = []
            feedback_map[sc].append({
                'step': row['step'],
                'text': row['feedback_text'],
                'timestamp': row['timestamp'],
            })
    except Exception:
        pass  # tabla puede no existir aun
    
    # Filtrar
    results = []
    for row in classifications:
        sc = row['shortcode']
        has_feedback = sc in feedback_map
        was_rejected = row['status'] in ('descartado_ia', 'rechazado')
        
        if only_feedback and not has_feedback:
            continue
        if only_rejected and not was_rejected:
            continue
        
        cats = json.loads(row['categorias']) if row['categorias'] else []
        ideas = json.loads(row['ideas_video']) if row['ideas_video'] else []
        
        results.append({
            'shortcode': sc,
            'profile': row['source_profile'],
            'type': row['source_type'],
            'likes': row['likes'],
            'status': row['status'],
            'valido': bool(row['valido']),
            'es_video_real': bool(row['es_video_real']),
            'confianza': row['confianza'],
            'categorias': cats,
            'descripcion': row['descripcion'],
            'ideas_video': ideas,
            'background_color': row['background_color'],
            'dia_especial': row['dia_especial'],
            'prompt_version': row['prompt_version'],
            'feedback': feedback_map.get(sc, []),
            'user_action': row['status'],  # what happened after classification
        })
    
    return results


def format_report(results):
    """Genera texto formateado para copiar y pegar."""
    lines = []
    lines.append("=" * 70)
    lines.append("EXPORT FEEDBACK - MEME REACTION V2")
    lines.append(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Total memes clasificados: {len(results)}")
    
    # Stats rapidas
    with_feedback = sum(1 for r in results if r['feedback'])
    rejected_by_user = sum(1 for r in results if r['status'] in ('descartado_ia', 'rechazado'))
    lines.append(f"Con feedback del usuario: {with_feedback}")
    lines.append(f"Rechazados/descartados: {rejected_by_user}")
    lines.append("=" * 70)
    lines.append("")
    
    for i, r in enumerate(results, 1):
        lines.append("-" * 70)
        lines.append(f"MEME {i}: {r['shortcode']}")
        lines.append(f"  Perfil: @{r['profile']} | Tipo: {r['type']} | Likes: {r['likes']:,}")
        lines.append(f"  Status actual: {r['status']}")
        lines.append(f"  Prompt version: {r['prompt_version']}")
        lines.append("")
        
        # Lo que dijo la IA
        lines.append("  [IA DIJO]:")
        lines.append(f"    Valido: {r['valido']} | Es video real: {r['es_video_real']}")
        lines.append(f"    Confianza: {r['confianza']}")
        lines.append(f"    Categorias: {', '.join(r['categorias'])}")
        lines.append(f"    Descripcion: {r['descripcion']}")
        lines.append(f"    Background: {r['background_color']}")
        if r['dia_especial']:
            lines.append(f"    Dia especial: {r['dia_especial']}")
        
        # Ideas de video
        lines.append("    Ideas video:")
        for idx, idea in enumerate(r['ideas_video'], 1):
            lines.append(f"      {idx}. {idea}")
        
        # Feedback del usuario
        if r['feedback']:
            lines.append("")
            lines.append("  [FEEDBACK USUARIO]:")
            for fb in r['feedback']:
                lines.append(f"    [{fb['step']}] {fb['text']}")
        
        # Accion final
        if r['status'] in ('descartado_ia', 'rechazado'):
            lines.append("")
            lines.append("  [RESULTADO]: RECHAZADO por el usuario")
        elif r['status'] == 'listo_clasificar':
            lines.append("")
            lines.append("  [RESULTADO]: MARCADO PARA RECLASIFICAR")
        
        lines.append("")
    
    # Resumen para el prompt
    lines.append("=" * 70)
    lines.append("RESUMEN PARA MEJORAR PROMPT:")
    lines.append("=" * 70)
    lines.append("")
    
    # Patrones de error
    if with_feedback > 0:
        lines.append("Feedback directo del usuario:")
        for r in results:
            for fb in r['feedback']:
                lines.append(f"  - [{r['shortcode']}] {fb['text']}")
        lines.append("")
    
    if rejected_by_user > 0:
        lines.append("Memes que la IA aprobo pero el usuario rechazo:")
        for r in results:
            if r['valido'] and r['status'] in ('descartado_ia', 'rechazado'):
                lines.append(f"  - [{r['shortcode']}] Cats: {', '.join(r['categorias'][:3])} | Desc: {r['descripcion'][:80]}...")
        lines.append("")
    
    reclassified = [r for r in results if r['status'] == 'listo_clasificar']
    if reclassified:
        lines.append("Memes marcados para reclasificar (algo estuvo mal):")
        for r in reclassified:
            fb_text = r['feedback'][0]['text'] if r['feedback'] else '(sin nota)'
            lines.append(f"  - [{r['shortcode']}] {fb_text}")
        lines.append("")
    
    lines.append("-" * 70)
    lines.append("Pega esto en el chat para que mejore el prompt de clasificacion.")
    lines.append("-" * 70)
    
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Export Feedback")
    parser.add_argument('--only-feedback', action='store_true',
                        help="Solo memes con notas del usuario")
    parser.add_argument('--only-rejected', action='store_true',
                        help="Solo rechazados/descartados")
    parser.add_argument('--version', type=int, default=None,
                        help="Filtrar por prompt version")
    parser.add_argument('--clipboard', action='store_true',
                        help="Copia al clipboard (requiere pyperclip)")
    parser.add_argument('--file', type=str, default=None,
                        help="Guardar a archivo")
    args = parser.parse_args()

    load_config()
    init_db()

    results = get_all_data(
        version=args.version,
        only_feedback=args.only_feedback,
        only_rejected=args.only_rejected
    )

    if not results:
        print("No hay clasificaciones para exportar.")
        return

    report = format_report(results)

    # Output
    if args.file:
        Path(args.file).write_text(report, encoding='utf-8')
        print(f"Guardado en: {args.file}")
        print(f"({len(results)} memes exportados)")
    elif args.clipboard:
        try:
            import pyperclip
            pyperclip.copy(report)
            print(f"Copiado al clipboard ({len(results)} memes)")
        except ImportError:
            print("pyperclip no instalado. Usa --file o sin flags para ver en terminal.")
            print(report)
    else:
        # Print a terminal
        print(report)


if __name__ == "__main__":
    main()
