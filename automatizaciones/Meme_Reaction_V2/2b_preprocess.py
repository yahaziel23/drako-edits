#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - 2b Preprocess

Preprocesa imagenes DESPUES de descarga y ANTES de batch_review.
Limpia bordes innecesarios y agrega marco apropiado segun el tipo de meme.

Algoritmo:
1. Auto-crop: recorta bordes uniformes desde las 4 esquinas hacia adentro
   hasta que cambia el color (tolerancia para JPEG artifacts).
   IMPORTANTE: retrocede N pixeles despues del crop para no cortar texto/contenido.
2. Detecta tipo de meme:
   - Tipo A (cuadro definido): despues del crop no hay bandas uniformes -> sin borde
   - Tipo B (texto en fondo solido + imagen abajo): detecta banda uniforme
     en la parte superior -> agrega borde del mismo color que ese fondo
3. Sobreescribe la imagen original con la version procesada.

Uso:
    python 2b_preprocess.py              # Procesa imagenes no procesadas
    python 2b_preprocess.py --reset      # Devuelve listo_clasificar a pendiente_review
    python 2b_preprocess.py --force      # Re-procesa todas (incluso ya procesadas)
    python 2b_preprocess.py --border 25  # Cambia el padding del borde (default: 20px)
    python 2b_preprocess.py --tolerance 20  # Tolerancia de color (default: 15)
    python 2b_preprocess.py --margin 8   # Pixeles de retroceso post-crop (default: 6)
    python 2b_preprocess.py --dry-run    # Muestra que haria sin modificar nada

Dependencias: Pillow, numpy
"""

import sys
import argparse
import numpy as np
from pathlib import Path
from PIL import Image

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db import init_db, get_db, update_meme_status
from utils.config import load_config
from utils.logger import setup_logger, get_logger

MEMES_DIR = SCRIPT_DIR / "memes_descargados"

# =============================================================================
# DATABASE: agregar columna preprocessed si no existe
# =============================================================================

def ensure_preprocessed_column():
    """Agrega columna 'preprocessed' a memes si no existe."""
    db = get_db()
    columns = [row[1] for row in db.execute("PRAGMA table_info(memes)").fetchall()]
    if 'preprocessed' not in columns:
        db.execute("ALTER TABLE memes ADD COLUMN preprocessed INTEGER DEFAULT 0")
        db.commit()


# =============================================================================
# AUTO-CROP: recortar bordes uniformes desde las 4 direcciones
# =============================================================================

def get_reference_color(img_array, corner='top_left', patch_size=5):
    """
    Obtiene el color de referencia de una esquina (promedio de un parche).
    Retorna array RGB.
    """
    h, w = img_array.shape[:2]
    ps = min(patch_size, h // 4, w // 4)
    
    if corner == 'top_left':
        patch = img_array[:ps, :ps]
    elif corner == 'top_right':
        patch = img_array[:ps, w-ps:]
    elif corner == 'bottom_left':
        patch = img_array[h-ps:, :ps]
    elif corner == 'bottom_right':
        patch = img_array[h-ps:, w-ps:]
    else:
        patch = img_array[:ps, :ps]
    
    return np.mean(patch, axis=(0, 1))


def get_consensus_color(img_array, patch_size=5, tolerance=15):
    """
    Determina el color de borde consensuado entre las 4 esquinas.
    Si al menos 2 esquinas son similares, ese es el color de borde.
    Retorna (color_rgb, tiene_borde_uniforme).
    """
    corners = ['top_left', 'top_right', 'bottom_left', 'bottom_right']
    colors = [get_reference_color(img_array, c, patch_size) for c in corners]
    
    groups = []
    used = [False] * 4
    
    for i in range(4):
        if used[i]:
            continue
        group = [i]
        used[i] = True
        for j in range(i + 1, 4):
            if not used[j] and np.max(np.abs(colors[i] - colors[j])) < tolerance:
                group.append(j)
                used[j] = True
        groups.append(group)
    
    largest_group = max(groups, key=len)
    
    if len(largest_group) >= 2:
        consensus_color = np.mean([colors[i] for i in largest_group], axis=0)
        return consensus_color, True
    else:
        return colors[0], False


def auto_crop(img_array, tolerance=15, min_content_ratio=0.3, margin=6):
    """
    Recorta bordes uniformes desde las 4 direcciones.
    
    CLAVE: despues de detectar donde cambia el color, RETROCEDE 'margin' pixeles
    para no cortar texto o contenido que esta sobre el mismo fondo.
    
    Args:
        img_array: numpy array (H, W, 3)
        tolerance: diferencia maxima en RGB para considerar "mismo color"
        min_content_ratio: minimo de contenido que debe quedar (evita crop excesivo)
        margin: pixeles de retroceso DESPUES del crop (safety buffer para texto)
    
    Returns:
        (top, bottom, left, right) - indices de crop
    """
    h, w = img_array.shape[:2]
    min_h = int(h * min_content_ratio)
    min_w = int(w * min_content_ratio)
    
    ref_color, has_border = get_consensus_color(img_array, tolerance=tolerance)
    
    if not has_border:
        return 0, h, 0, w
    
    # Crop desde arriba
    top = 0
    for row in range(h - min_h):
        row_mean = np.mean(img_array[row], axis=0)
        if np.max(np.abs(row_mean - ref_color)) > tolerance:
            break
        top = row + 1
    
    # Crop desde abajo
    bottom = h
    for row in range(h - 1, top + min_h - 1, -1):
        row_mean = np.mean(img_array[row], axis=0)
        if np.max(np.abs(row_mean - ref_color)) > tolerance:
            break
        bottom = row
    
    # Crop desde izquierda
    left = 0
    for col in range(w - min_w):
        col_mean = np.mean(img_array[:, col], axis=0)
        if np.max(np.abs(col_mean - ref_color)) > tolerance:
            break
        left = col + 1
    
    # Crop desde derecha
    right = w
    for col in range(w - 1, left + min_w - 1, -1):
        col_mean = np.mean(img_array[:, col], axis=0)
        if np.max(np.abs(col_mean - ref_color)) > tolerance:
            break
        right = col
    
    # === RETROCESO (margin) ===
    # Despues de detectar el borde exacto, retrocede unos pixeles
    # para no cortar texto/contenido que esta sobre el mismo fondo.
    # Solo retrocede si efectivamente hizo crop (no retrocede mas alla del original)
    if top > 0:
        top = max(0, top - margin)
    if bottom < h:
        bottom = min(h, bottom + margin)
    if left > 0:
        left = max(0, left - margin)
    if right < w:
        right = min(w, right + margin)
    
    return top, bottom, left, right


# =============================================================================
# DETECCION DE TIPO DE MEME
# =============================================================================

def detect_meme_type(img_array, band_threshold=0.12, uniformity_tolerance=20):
    """
    Detecta el tipo de meme despues del auto-crop.
    
    Tipo A (cuadro definido): no tiene bandas uniformes grandes
    Tipo B (texto + imagen): tiene banda uniforme en la parte superior
             (texto en fondo negro/blanco con imagen debajo)
    
    Returns:
        (tipo, info_dict)
        tipo: 'A' o 'B'
        info_dict: {'band_color': (r,g,b), 'band_height': px} para tipo B
    """
    h, w = img_array.shape[:2]
    
    # Buscar banda uniforme en la parte superior (hasta 40% de la imagen)
    max_band_search = int(h * 0.40)
    
    if max_band_search < 10:
        return 'A', {}
    
    # Tomar el color de la primera fila del contenido (ya cropeado)
    first_row_color = np.mean(img_array[0:3], axis=(0, 1))
    
    # Verificar si es un color "de fondo" (cerca de negro o blanco)
    is_dark = np.mean(first_row_color) < 60
    is_light = np.mean(first_row_color) > 200
    
    if not (is_dark or is_light):
        return 'A', {}
    
    # Buscar hasta donde llega la banda uniforme
    band_end = 0
    for row in range(max_band_search):
        row_mean = np.mean(img_array[row], axis=0)
        if np.max(np.abs(row_mean - first_row_color)) > uniformity_tolerance:
            break
        band_end = row + 1
    
    band_ratio = band_end / h
    
    if band_ratio >= band_threshold and band_ratio < 0.85:
        band_color = tuple(int(c) for c in first_row_color)
        return 'B', {
            'band_color': band_color,
            'band_height': band_end,
            'band_ratio': band_ratio,
            'is_dark': is_dark,
        }
    
    return 'A', {}


# =============================================================================
# AGREGAR BORDE
# =============================================================================

def add_border(img, border_size, color):
    """
    Agrega un borde uniforme alrededor de la imagen.
    """
    w, h = img.size
    new_w = w + (border_size * 2)
    new_h = h + (border_size * 2)
    
    bordered = Image.new('RGB', (new_w, new_h), color)
    bordered.paste(img, (border_size, border_size))
    
    return bordered


# =============================================================================
# PROCESAR UNA IMAGEN
# =============================================================================

def process_image(image_path, tolerance=15, border_size=20, margin=6, dry_run=False):
    """
    Pipeline completo de preprocesamiento para una imagen.
    
    1. Auto-crop (eliminar bordes uniformes, con margin de seguridad)
    2. Detectar tipo de meme
    3. Agregar borde si es necesario
    
    Args:
        image_path: Path al archivo .jpg
        tolerance: tolerancia de color para crop (default 15)
        border_size: tamano del borde a agregar para Tipo B (default 20px)
        margin: pixeles de retroceso post-crop (default 6)
        dry_run: si True, no modifica el archivo
    
    Returns:
        dict con info del procesamiento
    """
    log = get_logger()
    
    try:
        img = Image.open(image_path).convert('RGB')
    except Exception as e:
        log.error(f"No se pudo abrir {image_path.name}: {e}")
        return {'status': 'error', 'error': str(e)}
    
    original_size = img.size  # (w, h)
    img_array = np.array(img)
    
    # --- Paso 1: Auto-crop (con margin de seguridad) ---
    top, bottom, left, right = auto_crop(img_array, tolerance=tolerance, margin=margin)
    
    cropped = (top > 0 or bottom < img_array.shape[0] or 
               left > 0 or right < img_array.shape[1])
    
    if cropped:
        img_array = img_array[top:bottom, left:right]
        img = Image.fromarray(img_array)
    
    crop_info = {
        'cropped': cropped,
        'pixels_removed': {
            'top': top,
            'bottom': original_size[1] - bottom,
            'left': left,
            'right': original_size[0] - right,
        },
        'margin_applied': margin,
        'original_size': original_size,
        'cropped_size': img.size,
    }
    
    # --- Paso 2: Detectar tipo ---
    meme_type, type_info = detect_meme_type(img_array)
    
    # --- Paso 3: Agregar borde si corresponde ---
    border_added = False
    border_color = None
    
    if meme_type == 'B':
        # Tipo B: agregar borde del color del fondo del texto
        border_color = type_info['band_color']
        img = add_border(img, border_size, border_color)
        border_added = True
    # Tipo A: no agregar borde (ya tiene su cuadro definido)
    
    # --- Guardar ---
    if not dry_run:
        img.save(image_path, 'JPEG', quality=92)
    
    result = {
        'status': 'ok',
        'meme_type': meme_type,
        'crop': crop_info,
        'border_added': border_added,
        'border_color': border_color,
        'border_size': border_size if border_added else 0,
        'final_size': img.size,
        'type_info': type_info,
    }
    
    return result


# =============================================================================
# OBTENER MEMES A PROCESAR
# =============================================================================

def get_memes_to_process(force=False):
    db = get_db()
    if force:
        rows = db.execute("""
            SELECT shortcode, image_path FROM memes
            WHERE status IN ('pendiente_review', 'listo_clasificar')
            AND image_path IS NOT NULL
            ORDER BY likes DESC
        """).fetchall()
    else:
        rows = db.execute("""
            SELECT shortcode, image_path FROM memes
            WHERE status IN ('pendiente_review', 'listo_clasificar')
            AND (preprocessed IS NULL OR preprocessed = 0)
            AND image_path IS NOT NULL
            ORDER BY likes DESC
        """).fetchall()
    return rows


def reset_approved():
    db = get_db()
    cursor = db.execute("""
        UPDATE memes 
        SET status = 'pendiente_review', preprocessed = 0
        WHERE status = 'listo_clasificar'
    """)
    db.commit()
    return cursor.rowcount


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="2b Preprocess - Crop + Border")
    parser.add_argument('--reset', action='store_true',
                        help="Devuelve listo_clasificar a pendiente_review para re-procesar")
    parser.add_argument('--force', action='store_true',
                        help="Re-procesa todos (incluso ya procesados)")
    parser.add_argument('--border', type=int, default=20,
                        help="Tamano del borde en pixeles (default: 20)")
    parser.add_argument('--tolerance', type=int, default=15,
                        help="Tolerancia de color para crop (default: 15)")
    parser.add_argument('--margin', type=int, default=6,
                        help="Pixeles de retroceso post-crop para no cortar texto (default: 6)")
    parser.add_argument('--dry-run', action='store_true',
                        help="Muestra que haria sin modificar nada")
    args = parser.parse_args()

    # Setup
    setup_logger('2b_preprocess')
    log = get_logger()
    load_config()
    init_db()
    ensure_preprocessed_column()

    # Modo reset
    if args.reset:
        count = reset_approved()
        log.info(f"Reset: {count} memes movidos de listo_clasificar -> pendiente_review")
        log.info("Ahora corre: python 2b_preprocess.py (para re-procesarlos)")
        return

    # Obtener memes a procesar
    memes = get_memes_to_process(force=args.force)
    
    if not memes:
        log.info("No hay memes pendientes de preprocesamiento.")
        return

    log.info(f"Procesando {len(memes)} imagenes...")
    log.info(f"  Tolerancia: {args.tolerance}, Borde: {args.border}px, Margin: {args.margin}px")
    if args.dry_run:
        log.info("  [DRY RUN - no se modifican archivos]")
    print("")

    # Procesar cada imagen
    db = get_db()
    stats = {'total': 0, 'cropped': 0, 'bordered': 0, 'type_a': 0, 'type_b': 0, 'errors': 0}
    
    for row in memes:
        shortcode = row['shortcode']
        img_path = Path(row['image_path']) if row['image_path'] else MEMES_DIR / f"{shortcode}.jpg"
        
        if not img_path.exists():
            log.warning(f"  [{shortcode}] Imagen no encontrada: {img_path}")
            continue
        
        # Procesar
        result = process_image(
            img_path,
            tolerance=args.tolerance,
            border_size=args.border,
            margin=args.margin,
            dry_run=args.dry_run
        )
        
        stats['total'] += 1
        
        if result['status'] == 'error':
            stats['errors'] += 1
            continue
        
        # Estadisticas
        if result['crop']['cropped']:
            stats['cropped'] += 1
        if result['border_added']:
            stats['bordered'] += 1
        if result['meme_type'] == 'A':
            stats['type_a'] += 1
        else:
            stats['type_b'] += 1
        
        # Log por imagen
        crop_px = result['crop']['pixels_removed']
        crop_str = f"crop T:{crop_px['top']} B:{crop_px['bottom']} L:{crop_px['left']} R:{crop_px['right']}"
        border_str = f"borde {result['border_color']}" if result['border_added'] else "sin borde"
        size_str = f"{result['crop']['original_size']} -> {result['final_size']}"
        
        log.info(f"  [{shortcode}] Tipo {result['meme_type']} | {crop_str} | {border_str} | {size_str}")
        
        # Marcar como procesado en DB
        if not args.dry_run:
            db.execute(
                "UPDATE memes SET preprocessed = 1 WHERE shortcode = ?",
                (shortcode,)
            )
    
    if not args.dry_run:
        db.commit()
    
    # Resumen final
    print("")
    print("=" * 60)
    print("   PREPROCESS COMPLETADO")
    print("=" * 60)
    print(f"   Total procesadas:     {stats['total']}")
    print(f"   Con crop aplicado:    {stats['cropped']}")
    print(f"   Tipo A (sin borde):   {stats['type_a']}")
    print(f"   Tipo B (con borde):   {stats['type_b']}")
    print(f"   Errores:              {stats['errors']}")
    print(f"   Margin (retroceso):   {args.margin}px")
    if args.dry_run:
        print("   [DRY RUN - nada fue modificado]")
    print("=" * 60)
    print("")
    print("   Siguiente paso: python batch_review.py")
    print("")


if __name__ == "__main__":
    main()
