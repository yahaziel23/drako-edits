#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Drako Edits - Generador de Meme Reaction Videos

Formato: Imagen (meme) arriba (60%) + Video clip abajo (40%)
         Caption superpuesto en la frontera meme/video (opcional)
Duracion: min(video, audio) o custom.

Uso:
    python generate_meme_reaction.py

Preparar antes:
    - Imagenes en assets/meme_reaction/memes/
    - Clips catalogados en assets/meme_reaction/clips/
    - Audios en assets/meme_reaction/music/
"""

import sys
import io
import os
import json
import random
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip, AudioFileClip, ImageClip, CompositeVideoClip

# Fix para encoding en Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')


# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets" / "meme_reaction"
CLIPS_DIR = ASSETS_DIR / "clips"
MEMES_DIR = ASSETS_DIR / "memes"
MUSIC_DIR = ASSETS_DIR / "music"
OUTPUT_DIR = SCRIPT_DIR / "output" / "meme_reaction"
INDEX_FILE = ASSETS_DIR / "clips_index.json"

# Video config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30

# Layout proportions
MEME_RATIO = 0.60   # Meme ocupa 60% del alto
CLIP_RATIO = 0.40   # Video clip ocupa 40% del alto

# Font config
STROKE_WIDTH = 4

# Caption font size options
CAPTION_SIZES = {
    "S": 45,
    "M": 65,
    "L": 85,
    "XL": 110,
}