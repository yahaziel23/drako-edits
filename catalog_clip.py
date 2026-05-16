#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Catalogador interactivo de clips

Descarga un clip de YouTube Shorts (sin audio) y lo cataloga
automaticamente en clips_index.json con tags y captions.

Uso:
    python catalog_clip.py
    python catalog_clip.py --url "https://www.youtube.com/shorts/XXXXX"
"""

import json
import subprocess
import argparse
from pathlib import Path


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
CLIPS_DIR = SCRIPT_DIR / "assets" / "meme_reaction" / "clips"
INDEX_FILE = SCRIPT_DIR / "assets" / "meme_reaction" / "clips_index.json"

# Tags sugeridos por categoria
TAGS_SUGERIDOS = {
    "acciones": ["escribir", "buscar", "correr", "pelear", "bailar", "llorar",
                 "reir", "gritar", "pensar", "mirar", "esperar", "caer"],
    "emociones": ["epico", "triste", "enojado", "confundido", "sorprendido",
                  "feliz", "desesperado", "orgulloso", "nervioso", "basado"],
    "contexto": ["genio", "rapido", "lento", "fracaso", "victoria", "venganza",
                 "flexeo", "humillacion", "revelacion", "plot-twist"],
    "personaje": ["actor", "animacion", "gato", "perro", "anime",
                  "pelicula", "serie", "meme-clasico", "random"],
}


# =============================================================================
# FUNCIONES
# =============================================================================

def load_index():
    """Carga el indice de clips."""
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return []


def save_index(index):
    """Guarda el indice de clips."""
    INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def download_clip(url, filename):
    """Descarga un clip de YouTube sin audio."""
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = CLIPS_DIR / filename

    print(f"\n   Descargando clip...")
    cmd = [
        "yt-dlp",
        "-f", "bv[ext=mp4]",
        "-o", str(output_path),
        "--no-playlist",
        url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"   \u274c Error: {result.stderr[:200]}")
        return None

    if output_path.exists():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"   \u2705 Descargado: {filename} ({size_mb:.1f} MB)")
        return filename
    else:
        print(f"   \u274c No se descargo el archivo")
        return None


def show_tag_suggestions():
    """Muestra las sugerencias de tags."""
    print("\n   \ud83c\udff7\ufe0f  Tags sugeridos (puedes usar estos o inventar los tuyos):")
    print("   " + "-" * 50)
    for categoria, tags in TAGS_SUGERIDOS.items():
        print(f"   {categoria:12s}: {', '.join(tags)}")
    print("   " + "-" * 50)


def interactive_catalog():
    """Flujo interactivo para catalogar un clip."""
    print("\n" + "=" * 60)
    print("   DRAKO EDITS - CATALOGADOR DE CLIPS")
    print("=" * 60)

    # Cargar indice existente
    index = load_index()
    print(f"   Clips en catalogo: {len(index)}")

    # 1. Pedir URL
    print("\n\u2501\u2501\u2501 PASO 1: Link del Short \u2501\u2501\u2501")
    url = input("\n   Pega el link del YouTube Short: ").strip()
    if not url:
        print("   \u274c No pusiste link. Saliendo.")
        return

    # 2. Pedir nombre del archivo
    print("\n\u2501\u2501\u2501 PASO 2: Nombre del archivo \u2501\u2501\u2501")
    print("   (sin extension, usa guion_bajo, ej: jim_carrey_typing)")
    filename = input("   Nombre: ").strip()
    if not filename:
        print("   \u274c No pusiste nombre. Saliendo.")
        return
    if not filename.endswith(".mp4"):
        filename += ".mp4"

    # Verificar si ya existe
    existing_files = {entry["file"] for entry in index}
    if filename in existing_files:
        print(f"   \u26a0\ufe0f  '{filename}' ya existe en el catalogo. Se actualizara.")

    # 3. Descargar
    print("\n\u2501\u2501\u2501 PASO 3: Descargando \u2501\u2501\u2501")
    downloaded = download_clip(url, filename)
    if not downloaded:
        cont = input("   \u00bfContinuar catalogando sin descarga? (s/n): ").strip().lower()
        if cont != 's':
            return

    # 4. Tags
    print("\n\u2501\u2501\u2501 PASO 4: Tags \u2501\u2501\u2501")
    show_tag_suggestions()
    print("\n   \u00bfQue describe este clip? (separados por coma)")
    print("   Ejemplo: escribir, rapido, genio, epico")
    tags_input = input("   Tags: ").strip()
    tags = [t.strip().lower() for t in tags_input.split(",") if t.strip()]
    if not tags:
        print("   \u26a0\ufe0f  Sin tags, usando 'sin-categoria'")
        tags = ["sin-categoria"]

    # 5. Captions
    print("\n\u2501\u2501\u2501 PASO 5: Captions \u2501\u2501\u2501")
    print("   Escribe captions que funcionen con este clip.")
    print("   (uno por linea, ENTER vacio para terminar)")
    print("")
    print("   Ejemplos para inspirarte:")
    print("     - 'El men que escribio el post:'")
    print("     - 'Yo buscando la respuesta:'")
    print("     - 'El que redacto esa respuesta epica:'")
    print("")

    captions = []
    while True:
        caption = input("   > ").strip()
        if not caption:
            break
        captions.append(caption)

    if not captions:
        print("   \u26a0\ufe0f  Sin captions por ahora (puedes agregarlos despues).")

    # 6. Descripcion rapida (opcional)
    print("\n\u2501\u2501\u2501 PASO 6: Descripcion (opcional) \u2501\u2501\u2501")
    print("   Una linea describiendo el clip (para que recuerdes que es)")
    print("   Ejemplo: 'Jim Carrey escribiendo rapido en Todo Poderoso'")
    description = input("   Descripcion: ").strip()

    # 7. Guardar
    entry = {
        "file": filename,
        "url": url,
        "tags": tags,
        "captions": captions,
        "description": description,
    }

    # Actualizar si ya existe, agregar si no
    updated = False
    for i, existing in enumerate(index):
        if existing["file"] == filename:
            index[i] = entry
            updated = True
            break
    if not updated:
        index.append(entry)

    save_index(index)

    # Resumen
    print(f"\n\n{'='*60}")
    print(f"   \u2705 CLIP CATALOGADO")
    print(f"{'='*60}")
    print(f"   Archivo:     {filename}")
    print(f"   Tags:        {', '.join(tags)}")
    print(f"   Captions:    {len(captions)}")
    print(f"   Descripcion: {description or '(ninguna)'}")
    print(f"   Total clips: {len(index)}")
    print(f"{'='*60}")

    # Preguntar si quiere agregar otro
    otro = input("\n   \u00bfCatalogar otro clip? (s/n): ").strip().lower()
    if otro == 's':
        interactive_catalog()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drako Edits - Catalogar clip")
    parser.add_argument("--url", type=str, default=None,
                        help="URL del YouTube Short (si no se da, se pide interactivamente)")
    args = parser.parse_args()

    if args.url:
        # Modo rapido: solo pasa la URL, el resto interactivo
        print(f"   URL: {args.url}")

    interactive_catalog()
