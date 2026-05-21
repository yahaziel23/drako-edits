#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paso 3.5: Revisar Clasificaciones de la IA

Abre cada imagen clasificada y muestra lo que la IA dijo.
Permite validar si la clasificacion tiene sentido o anotar problemas
para ajustar el prompt del paso 3.

Controles:
  Enter / s  = OK (la IA acerto)
  n / m      = MAL (la IA se equivoco, anota por que)
  q          = SALIR

Output: historial/review_clasificacion.json

Uso:
    python 3.5_review_clasificacion.py
    python 3.5_review_clasificacion.py --max 10
    python 3.5_review_clasificacion.py --solo-errores   # Solo los marcados MAL
    python 3.5_review_clasificacion.py --sin-abrir
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
MEMES_DIR = SCRIPT_DIR / "memes_descargados"
HISTORIAL_DIR = SCRIPT_DIR / "historial"
CLASIFICACIONES_FILE = HISTORIAL_DIR / "clasificaciones.json"
REVIEW_FILE = HISTORIAL_DIR / "review_clasificacion.json"


# =============================================================================
# FUNCIONES
# =============================================================================

def load_clasificaciones():
    if CLASIFICACIONES_FILE.exists():
        try:
            return json.loads(CLASIFICACIONES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clasificados": [], "skipped_video_content": [], "errores": []}


def load_review():
    if REVIEW_FILE.exists():
        try:
            return json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"correctos": [], "incorrectos": []}


def save_review(data):
    HISTORIAL_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def open_image(image_path):
    try:
        if sys.platform == "win32":
            os.startfile(str(image_path))
        elif sys.platform == "darwin":
            os.system(f'open "{image_path}"')
        else:
            os.system(f'xdg-open "{image_path}"')
    except Exception:
        pass


def wrap_text(text, width=90, indent="         "):
    """Wrap text to fit terminal width."""
    lines = []
    words = text.split()
    line = indent
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = indent + word
        else:
            line += (" " + word) if line.strip() else (indent + word)
    if line.strip():
        lines.append(line)
    return "\n".join(lines)


def format_clasificacion(item):
    """Formatea la clasificacion para mostrar bonito en terminal."""
    lines = []
    lines.append(f"       Categorias: {', '.join(item.get('categorias', []))}")
    lines.append(f"       Confianza:  {item.get('confianza', '?')}")
    lines.append(f"       Source:     {item.get('source_type', '?')}")
    lines.append(f"       Background: {item.get('background_color', '?')}")

    # Dia especial
    dia = item.get("dia_especial")
    if dia:
        lines.append(f"       Dia especial: {dia}")

    # Descripcion
    desc = item.get("descripcion", "(sin descripcion)")
    lines.append(f"       Descripcion:")
    lines.append(wrap_text(desc))

    # Franjas negras
    franjas = item.get("franjas_negras", {})
    if franjas.get("tiene"):
        arriba = franjas.get("arriba", franjas.get("arriba_px_pct", "?"))
        abajo = franjas.get("abajo", franjas.get("abajo_px_pct", "?"))
        crop_arr = franjas.get("crop_arriba", "?")
        crop_abj = franjas.get("crop_abajo", "?")
        lines.append(f"       Franjas:    arriba={arriba} (crop={crop_arr}), abajo={abajo} (crop={crop_abj})")
    else:
        lines.append(f"       Franjas:    No tiene")

    # Ideas de video
    ideas = item.get("ideas_video", [])
    if ideas:
        lines.append(f"")
        lines.append(f"       IDEAS DE VIDEO ({len(ideas)}):")
        for j, idea in enumerate(ideas):
            lines.append(f"       [{j+1}] Formato: {idea.get('formato', '?')}")
            caption = idea.get('caption_sugerido')
            if caption:
                lines.append(f"           Caption: \"{caption}\"")
            clip = idea.get('clip_ideal', '')
            if clip:
                lines.append(f"           Clip: {clip}")
            desc_idea = idea.get('descripcion_idea', '')
            if desc_idea:
                lines.append(f"           Por que: {desc_idea}")

    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def main():
    parser = argparse.ArgumentParser(description="Paso 3.5: Revisar clasificaciones IA")
    parser.add_argument("--max", type=int, default=None,
                        help="Maximo de clasificaciones a revisar")
    parser.add_argument("--sin-abrir", action="store_true",
                        help="No abre la imagen")
    parser.add_argument("--solo-errores", action="store_true",
                        help="Solo muestra los que marcaste como MAL previamente")
    args = parser.parse_args()

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - PASO 3.5: REVIEW CLASIFICACION IA")
    print(SEPARATOR_EQ)
    print("   Controles:")
    print("     s / Enter  = OK (la IA acerto)")
    print("     n / m      = MAL (la IA se equivoco)")
    print("     q          = SALIR")
    print(SEPARATOR_EQ)

    # Cargar datos
    clasificaciones = load_clasificaciones()
    review_data = load_review()

    clasificados = clasificaciones.get("clasificados", [])
    if not clasificados:
        print("\n   [!] No hay clasificaciones para revisar.")
        print("       Ejecuta primero: python 3_classify_meme.py")
        return

    # Ya revisados
    ya_revisados = set()
    for item in review_data.get("correctos", []):
        ya_revisados.add(item["shortcode"])
    for item in review_data.get("incorrectos", []):
        ya_revisados.add(item["shortcode"])

    if args.solo_errores:
        # Mostrar solo los marcados como incorrectos
        incorrectos = review_data.get("incorrectos", [])
        if not incorrectos:
            print("\n   [!] No hay clasificaciones marcadas como MAL.")
            return
        print(f"\n   Mostrando {len(incorrectos)} clasificaciones marcadas MAL:")
        print(SEPARATOR)
        for i, item in enumerate(incorrectos):
            sc = item["shortcode"]
            nota = item.get("nota", "")
            # Buscar clasificacion original
            original = next((c for c in clasificados if c["shortcode"] == sc), None)
            print(f"\n   [{i+1}/{len(incorrectos)}] {sc}")
            if original:
                print(format_clasificacion(original))
            print(f"\n       TU NOTA: {nota}")
            # Abrir imagen
            img_path = MEMES_DIR / f"{sc}.jpg"
            if img_path.exists() and not args.sin_abrir:
                open_image(img_path)
            input("       [Enter para continuar]")
        return

    # Filtrar pendientes de revisar
    pending = [c for c in clasificados if c["shortcode"] not in ya_revisados]

    if not pending:
        print("\n   [!] Todas las clasificaciones ya fueron revisadas.")
        total_ok = len(review_data.get("correctos", []))
        total_mal = len(review_data.get("incorrectos", []))
        print(f"       OK: {total_ok}  |  MAL: {total_mal}")
        if total_mal > 0:
            print(f"       Usa --solo-errores para ver los que fallaron")
        return

    if args.max:
        pending = pending[:args.max]

    print(f"\n   Clasificaciones por revisar: {len(pending)}")
    print(f"   Ya revisadas: OK={len(review_data.get('correctos', []))} | MAL={len(review_data.get('incorrectos', []))}")
    print(SEPARATOR)

    stats = {"ok": 0, "mal": 0}

    for i, item in enumerate(pending):
        shortcode = item["shortcode"]
        img_path = MEMES_DIR / f"{shortcode}.jpg"

        print(f"\n   [{i+1}/{len(pending)}] {shortcode}")
        print(SEPARATOR)
        print(format_clasificacion(item))
        print(SEPARATOR)

        # Abrir imagen
        if img_path.exists() and not args.sin_abrir:
            open_image(img_path)
        elif not img_path.exists():
            print("       [!] Imagen no encontrada (fue descartada?)")

        # Pedir decision
        while True:
            choice = input("       OK o MAL? (s/Enter=OK, n/m=MAL, q=salir): ").strip().lower()
            if choice in ("", "s", "si", "y", "ok"):
                stats["ok"] += 1
                review_data["correctos"].append({
                    "shortcode": shortcode,
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                print("       -> OK")
                break
            elif choice in ("n", "m", "no", "mal"):
                nota = input("       Que estuvo mal? (breve): ").strip()
                stats["mal"] += 1
                review_data["incorrectos"].append({
                    "shortcode": shortcode,
                    "nota": nota,
                    "categorias_ia": item.get("categorias", []),
                    "descripcion_ia": item.get("descripcion", ""),
                    "ideas_ia": item.get("ideas_video", []),
                    "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
                print("       -> MAL (anotado)")
                break
            elif choice in ("q", "quit", "salir"):
                print("\n   [SALIR] Guardando progreso...")
                save_review(review_data)
                _print_summary(stats, review_data)
                return
            else:
                print("       [?] Usa: s/Enter=OK, n/m=MAL, q=salir")

        save_review(review_data)

    _print_summary(stats, review_data)


def _print_summary(stats, review_data):
    print("")
    print(SEPARATOR_EQ)
    print("   RESUMEN")
    print(SEPARATOR_EQ)
    print(f"   Esta sesion: OK={stats['ok']} | MAL={stats['mal']}")
    total_ok = len(review_data.get("correctos", []))
    total_mal = len(review_data.get("incorrectos", []))
    print(f"   Total historico: OK={total_ok} | MAL={total_mal}")
    if total_ok + total_mal > 0:
        accuracy = total_ok / (total_ok + total_mal) * 100
        print(f"   Accuracy del prompt: {accuracy:.0f}%")
    if total_mal > 0:
        print(f"\n   Ultimas notas de errores:")
        for item in review_data.get("incorrectos", [])[-5:]:
            print(f"     - {item['shortcode']}: {item.get('nota', '')}")
    print(f"   Guardado en: {REVIEW_FILE}")
    print(SEPARATOR_EQ)


if __name__ == "__main__":
    main()
