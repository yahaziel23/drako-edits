#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Catalogar Clips de Reaccion

Script conversacional para catalogar clips de video para el pipeline de meme reaction.
Flujo por clip:
  1. Navegas por carpetas y eliges un video
  2. Se abre para que lo veas
  3. Escribes una descripcion con tus palabras
  4. La IA la mejora/refina (texto, no cuesta nada)
  5. Confirmas o iteras (como una conversacion)
  6. Asignas categorias
  7. Se COPIA a clips/ dentro de Meme_Reaction
  8. Se guarda en catalogo_clips.json (path apunta a la copia local)

Uso:
    python catalogar_clips.py
    python catalogar_clips.py --videos-dir "../../tools_output/videos"

Dependencias: openai, python-dotenv
"""

import json
import sys
import os
import shutil
import argparse
from pathlib import Path
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    print("   [X] Necesitas instalar openai:")
    print("       pip install openai")
    sys.exit(1)

from dotenv import load_dotenv


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # drako-edits/
CATALOGO_FILE = SCRIPT_DIR / "catalogo_clips.json"
CLIPS_DIR = SCRIPT_DIR / "clips"  # Copia local de clips catalogados
ENV_FILE = PROJECT_ROOT / ".env"

# Default: carpeta de videos del proyecto general
DEFAULT_VIDEOS_DIR = PROJECT_ROOT / "tools_output" / "videos"

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}

CATEGORIAS = [
    "humor_absurdo",
    "humor_dark",
    "cringe",
    "sad_funny",
    "wholesome",
    "plot_twist",
    "relatable",
    "rage",
    "sus",
    "intellectual",
]

MODEL = "gpt-4o-mini"  # Texto puro, barato


# =============================================================================
# FUNCIONES - CATALOGO
# =============================================================================

def load_catalogo():
    if CATALOGO_FILE.exists():
        try:
            return json.loads(CATALOGO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"clips": []}


def save_catalogo(data):
    CATALOGO_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_cataloged_filenames(catalogo):
    """Obtiene filenames ORIGINALES ya catalogados para no repetir."""
    names = set()
    for clip in catalogo.get("clips", []):
        # Usar filename_original (nombre real del source) para comparar en browse_folder
        if "filename_original" in clip:
            names.add(clip["filename_original"])
        else:
            # Fallback para clips viejos que no tengan filename_original
            names.add(clip.get("filename", ""))
    return names


# =============================================================================
# FUNCIONES - NAVEGACION DE CARPETAS
# =============================================================================

def browse_folder(root_dir, already_cataloged):
    """
    Navega carpetas y selecciona un video.
    Patron browse_folder del proyecto Drako Edits.
    """
    current_dir = root_dir

    while True:
        print(f"\n   Carpeta: {current_dir.relative_to(root_dir.parent)}")
        print("   " + "-" * 50)

        # Listar contenido
        items = sorted(current_dir.iterdir())
        folders = [f for f in items if f.is_dir() and f.name != '.gitkeep']
        files = [f for f in items if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS]

        options = []

        # Opcion para volver
        if current_dir != root_dir:
            print("   0. [<] Volver arriba")

        # Carpetas
        for i, folder in enumerate(folders, 1):
            n_videos = sum(1 for f in folder.rglob('*') if f.suffix.lower() in VIDEO_EXTENSIONS)
            print(f"   {i}. [>] {folder.name}/ ({n_videos} videos)")
            options.append(("folder", folder))

        # Archivos
        for i, file in enumerate(files, len(folders) + 1):
            cataloged = " [YA CATALOGADO]" if file.name in already_cataloged else ""
            size_mb = file.stat().st_size / (1024 * 1024)
            print(f"   {i}. {file.name} ({size_mb:.1f}MB){cataloged}")
            options.append(("file", file))

        if not options:
            print("   (carpeta vacia)")
            if current_dir != root_dir:
                current_dir = current_dir.parent
                continue
            return None

        print("")
        choice = input("   Elige (numero, o 'q' para salir): ").strip()

        if choice.lower() in ('q', 'quit', 'salir'):
            return None

        if choice == '0' and current_dir != root_dir:
            current_dir = current_dir.parent
            continue

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                tipo, path = options[idx]
                if tipo == "folder":
                    current_dir = path
                else:
                    return path
            else:
                print("   [?] Numero fuera de rango")
        except ValueError:
            print("   [?] Ingresa un numero")


# =============================================================================
# FUNCIONES - IA (DESCRIPCION)
# =============================================================================

def improve_description(client, user_description, filename):
    """
    La IA mejora la descripcion del usuario.
    Retorna la version mejorada.
    """
    prompt = f"""Eres un asistente que ayuda a catalogar clips de video para un proyecto de memes.
El usuario te da una descripcion informal de un clip de reaccion y tu la mejoras para que sea:
- Clara y concisa (1-2 oraciones)
- Descriptiva de la ACCION/EMOCION del clip (no del archivo)
- Util para que una IA pueda matchear este clip con un meme apropiado
- En espanol

Nombre del archivo: {filename}
Descripcion del usuario: "{user_description}"

Responde SOLO con la descripcion mejorada (sin comillas, sin explicacion)."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"   [!] Error IA: {e}")
        return user_description


def refine_description(client, current_description, user_feedback):
    """
    Refina la descripcion basandose en feedback del usuario.
    """
    prompt = f"""La descripcion actual de un clip de reaccion es:
"{current_description}"

El usuario quiere ajustarla. Su feedback:
"{user_feedback}"

Reescribe la descripcion incorporando el feedback. Mismas reglas:
- Clara y concisa (1-2 oraciones)
- Descriptiva de la accion/emocion
- En espanol

Responde SOLO con la nueva descripcion."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"   [!] Error IA: {e}")
        return current_description


# =============================================================================
# FUNCIONES - ABRIR VIDEO
# =============================================================================

def open_video(video_path):
    """Abre video con el reproductor por defecto."""
    try:
        if sys.platform == "win32":
            os.startfile(str(video_path))
        elif sys.platform == "darwin":
            os.system(f'open "{video_path}"')
        else:
            os.system(f'xdg-open "{video_path}"')
    except Exception:
        pass


def copy_to_clips(source_path, clip_id):
    """
    Copia el video a la carpeta local clips/ con nombre basado en el ID.
    Mantiene la extension original.
    Returns: path relativo dentro de clips/ (para guardar en catalogo)
    """
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
    ext = source_path.suffix.lower()
    dest_filename = f"{clip_id}{ext}"
    dest_path = CLIPS_DIR / dest_filename

    # Si ya existe (re-catalogo), sobreescribir
    shutil.copy2(source_path, dest_path)
    return dest_filename


# =============================================================================
# MAIN
# =============================================================================

SEPARATOR = "-" * 60
SEPARATOR_EQ = "=" * 60


def catalog_one_clip(client, video_path, videos_dir, catalogo):
    """
    Flujo conversacional para catalogar UN clip.
    Returns: dict del clip catalogado, o None si se cancela.
    """
    filename = video_path.name

    print(f"\n{SEPARATOR}")
    print(f"   CATALOGANDO: {filename}")
    print(SEPARATOR)

    # Abrir video
    print("   Abriendo video...")
    open_video(video_path)

    # === PASO 1: Descripcion del usuario ===
    print("\n   Describe el clip con tus palabras (que pasa, que emocion transmite):")
    user_desc = input("   > ").strip()
    if not user_desc:
        print("   [!] Sin descripcion, saltando...")
        return None

    # === PASO 2: IA mejora la descripcion ===
    print("\n   Mejorando descripcion con IA...")
    improved = improve_description(client, user_desc, filename)
    print(f"\n   IA dice: \"{improved}\"")

    # === PASO 3: Conversacion iterativa ===
    current_desc = improved
    while True:
        print("\n   Opciones:")
        print("     Enter / s = OK, usar esta descripcion")
        print("     [texto]   = Dar feedback para ajustar")
        print("     o         = Usar mi descripcion original")
        print("     q         = Cancelar este clip")

        choice = input("   > ").strip()

        if choice.lower() in ('', 's', 'si', 'ok'):
            break
        elif choice.lower() == 'o':
            current_desc = user_desc
            print(f"   OK, usando: \"{current_desc}\"")
            break
        elif choice.lower() == 'q':
            return None
        else:
            # El texto es feedback
            print("   Refinando...")
            current_desc = refine_description(client, current_desc, choice)
            print(f"\n   IA dice: \"{current_desc}\"")

    # === PASO 4: Categorias ===
    print(f"\n   Categorias disponibles:")
    for i, cat in enumerate(CATEGORIAS, 1):
        print(f"     {i:2d}. {cat}")

    print("\n   Elige categorias (numeros separados por coma, ej: 1,3,7):")
    cat_input = input("   > ").strip()

    selected_cats = []
    try:
        indices = [int(x.strip()) - 1 for x in cat_input.split(",")]
        for idx in indices:
            if 0 <= idx < len(CATEGORIAS):
                selected_cats.append(CATEGORIAS[idx])
    except ValueError:
        pass

    if not selected_cats:
        print("   [!] Sin categorias validas, saltando...")
        return None

    # === PASO 5: Generar ID y confirmar ===
    existing_ids = {clip["id"] for clip in catalogo.get("clips", [])}
    base_id = video_path.stem.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")[:30]
    clip_id = base_id
    counter = 1
    while clip_id in existing_ids:
        clip_id = f"{base_id}_{counter:02d}"
        counter += 1

    print(f"\n{SEPARATOR}")
    print(f"   RESUMEN DEL CLIP:")
    print(f"   ID: {clip_id}")
    print(f"   Archivo original: {filename}")
    print(f"   Se copiara a: clips/{clip_id}{video_path.suffix.lower()}")
    print(f"   Descripcion: \"{current_desc}\"")
    print(f"   Categorias: {', '.join(selected_cats)}")
    print(SEPARATOR)

    confirm = input("   Guardar? (Enter/s=si, n=no): ").strip().lower()
    if confirm in ('n', 'no'):
        print("   [!] Cancelado")
        return None

    # === PASO 6: Copiar video a clips/ ===
    print("   Copiando video a clips/...")
    local_filename = copy_to_clips(video_path, clip_id)
    print(f"   [OK] Copiado: clips/{local_filename}")

    clip_data = {
        "id": clip_id,
        "filename": local_filename,
        "filename_original": filename,
        "categorias": selected_cats,
        "descripcion": current_desc,
        "descripcion_original": user_desc,
        "usado_count": 0,
        "fecha_catalogado": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    return clip_data


def main():
    parser = argparse.ArgumentParser(description="Catalogar clips de reaccion")
    parser.add_argument("--videos-dir", type=str, default=None,
                        help=f"Carpeta raiz de videos (default: {DEFAULT_VIDEOS_DIR})")
    args = parser.parse_args()

    videos_dir = Path(args.videos_dir) if args.videos_dir else DEFAULT_VIDEOS_DIR

    if not videos_dir.exists():
        print(f"   [X] Carpeta de videos no encontrada: {videos_dir}")
        return

    print("")
    print(SEPARATOR_EQ)
    print("   MEME REACTION - CATALOGAR CLIPS DE REACCION")
    print(SEPARATOR_EQ)
    print(f"   Carpeta de videos: {videos_dir}")
    print(f"   Catalogo: {CATALOGO_FILE}")
    print(f"   Clips copiados a: {CLIPS_DIR}")
    print("")
    print("   Flujo por clip:")
    print("     1. Eliges video navegando carpetas")
    print("     2. Se abre para que lo veas")
    print("     3. Escribes descripcion con tus palabras")
    print("     4. La IA la mejora (conversacion iterativa)")
    print("     5. Asignas categorias")
    print("     6. Se COPIA a clips/ (el pipeline usa esta copia)")
    print("     7. Se guarda en catalogo_clips.json")

    # Cargar .env
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        print(f"   [!] No se encontro .env en: {ENV_FILE}")

    # Verificar API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("\n   [X] OPENAI_API_KEY no configurada en .env")
        return
    print(f"   OpenAI: ...{api_key[-4:]} (modelo: {MODEL})")

    # Cargar catalogo
    catalogo = load_catalogo()
    already_cataloged = get_cataloged_filenames(catalogo)
    print(f"   Clips ya catalogados: {len(already_cataloged)}")

    # Crear cliente
    client = OpenAI(api_key=api_key)

    # Loop principal
    clips_added = 0
    print(f"\n{SEPARATOR_EQ}")
    print("   SELECCIONA UN VIDEO PARA CATALOGAR")
    print(SEPARATOR_EQ)

    while True:
        video_path = browse_folder(videos_dir, already_cataloged)

        if video_path is None:
            break

        # Verificar si ya esta catalogado
        if video_path.name in already_cataloged:
            print(f"\n   [!] Este clip ya esta catalogado. Catalogar de nuevo? (s/n)")
            if input("   > ").strip().lower() not in ('s', 'si'):
                continue

        # Catalogar
        clip_data = catalog_one_clip(client, video_path, videos_dir, catalogo)

        if clip_data:
            catalogo["clips"].append(clip_data)
            already_cataloged.add(clip_data["filename_original"])
            save_catalogo(catalogo)
            clips_added += 1
            print(f"\n   [OK] Clip guardado! (Total en catalogo: {len(catalogo['clips'])})")

        # Continuar?
        print("\n   Catalogar otro? (Enter=si, q=salir)")
        if input("   > ").strip().lower() in ('q', 'quit', 'salir'):
            break

    # Resumen
    print(f"\n{SEPARATOR_EQ}")
    print("   RESUMEN")
    print(SEPARATOR_EQ)
    print(f"   Clips catalogados esta sesion: {clips_added}")
    print(f"   Total en catalogo: {len(catalogo.get('clips', []))}")

    if catalogo.get("clips"):
        print("\n   Distribucion por categoria:")
        cat_counts = {}
        for clip in catalogo["clips"]:
            for cat in clip.get("categorias", []):
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            print(f"     {cat}: {count}")

    print(f"   Guardado en: {CATALOGO_FILE}")
    print(SEPARATOR_EQ)


if __name__ == "__main__":
    main()
