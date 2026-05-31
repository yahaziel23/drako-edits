#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Meme Reaction V2 - Database Module (SQLite)

Base de datos central que reemplaza todos los JSONs de historial.
Maneja schema, conexión, y helpers para queries comunes.

Uso:
    from utils.db import get_db, init_db
    
    # Inicializar (crea tablas si no existen)
    init_db()
    
    # Obtener conexión
    db = get_db()
    db.execute("INSERT INTO memes ...")
    db.commit()
"""

import sqlite3
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

# =============================================================================
# CONFIGURACION
# =============================================================================

SCRIPT_DIR = Path(__file__).parent.parent  # Meme_Reaction_V2/
DB_PATH = SCRIPT_DIR / "meme_reaction.db"

# Singleton connection
_connection = None


# =============================================================================
# SCHEMA
# =============================================================================

SCHEMA = """
-- =========================================================================
-- MEMES: Tabla principal. Cada post scrapeado es una fila.
-- =========================================================================
CREATE TABLE IF NOT EXISTS memes (
    shortcode       TEXT PRIMARY KEY,
    source_profile  TEXT NOT NULL,
    source_type     TEXT NOT NULL DEFAULT 'desconocido',  -- 'foto' | 'frame' | 'carousel'
    source_url      TEXT,
    likes           INTEGER DEFAULT 0,
    comments        INTEGER DEFAULT 0,
    views           INTEGER,
    status          TEXT NOT NULL DEFAULT 'por_descargar',
    -- Status values:
    --   por_descargar -> descargado -> pendiente_review | listo_clasificar
    --   -> clasificado -> pendiente_match -> matched_auto | match_review | buscar_clip
    --   -> por_generar -> generado -> por_subir -> subido
    --   Terminal: rechazado, descartado_ia
    image_path      TEXT,
    image_hash      TEXT,         -- SHA-256 del archivo (para cache/dedup)
    scraped_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    downloaded_at   TIMESTAMP,
    classified_at   TIMESTAMP,
    matched_at      TIMESTAMP,
    generated_at    TIMESTAMP,
    uploaded_at     TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- CLASIFICACIONES: Resultado del análisis IA (GPT-4o Vision)
-- =========================================================================
CREATE TABLE IF NOT EXISTS clasificaciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode       TEXT NOT NULL UNIQUE REFERENCES memes(shortcode),
    valido          BOOLEAN NOT NULL DEFAULT 1,
    es_video_real   BOOLEAN NOT NULL DEFAULT 0,
    categorias      TEXT,           -- JSON array: ["humor_dark", "cringe"]
    confianza       REAL DEFAULT 0.0,
    descripcion     TEXT,           -- Descripción detallada para caption/match
    ideas_video     TEXT,           -- JSON array de ideas creativas
    background_color TEXT DEFAULT 'blanco',
    franjas_negras  TEXT,           -- JSON: {tiene, arriba, abajo, crop_arriba, crop_abajo}
    dia_especial    TEXT,
    prompt_version_id INTEGER REFERENCES prompt_versions(id),
    tokens_used     INTEGER DEFAULT 0,
    classified_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- CLIPS: Catálogo de clips de reacción disponibles
-- =========================================================================
CREATE TABLE IF NOT EXISTS clips (
    id              TEXT PRIMARY KEY,  -- ID único del clip (ej: "laugh_01")
    descripcion     TEXT NOT NULL,
    categorias      TEXT,             -- JSON array
    filename        TEXT NOT NULL,    -- Nombre en clips/
    filename_original TEXT,           -- Nombre original del source
    source_path     TEXT,             -- Path original de donde se copió
    duracion_s      REAL,             -- Duración en segundos
    usado_count     INTEGER DEFAULT 0,
    catalogado_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- MATCHES: Relación meme <-> clip (resultado del paso 4)
-- =========================================================================
CREATE TABLE IF NOT EXISTS matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode       TEXT NOT NULL REFERENCES memes(shortcode),
    clip_id         TEXT REFERENCES clips(id),
    accuracy        REAL DEFAULT 0.0,   -- 0-100%
    caption         TEXT,               -- Caption para el video (o NULL)
    caption_size    TEXT DEFAULT 'M',   -- S/M/L/XL
    match_type      TEXT NOT NULL DEFAULT 'manual',  -- 'auto' | 'manual' | 'review'
    ia_suggestion   TEXT,               -- JSON: lo que la IA sugirió originalmente
    clip_ideal      TEXT,               -- Descripción del clip ideal (para clip_finder)
    ideas_alternativas TEXT,            -- JSON array
    status          TEXT NOT NULL DEFAULT 'pendiente',
    -- Status: pendiente | aceptado | rechazado | buscar_clip
    matched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- VIDEOS_GENERADOS: Videos producidos por paso 7
-- =========================================================================
CREATE TABLE IF NOT EXISTS videos_generados (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode       TEXT NOT NULL REFERENCES memes(shortcode),
    match_id        INTEGER REFERENCES matches(id),
    output_path     TEXT NOT NULL,
    config_json     TEXT,             -- JSON con toda la config usada
    duracion_s      REAL,
    width           INTEGER DEFAULT 1080,
    height          INTEGER DEFAULT 1920,
    variante_num    INTEGER DEFAULT 1,  -- Para A/B testing (variante 1, 2, 3)
    selected        BOOLEAN DEFAULT 0,  -- Si el usuario eligió esta variante
    generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- UPLOADS: Registro de subidas a redes sociales
-- =========================================================================
CREATE TABLE IF NOT EXISTS uploads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER NOT NULL REFERENCES videos_generados(id),
    platform        TEXT NOT NULL,      -- 'youtube' | 'tiktok' | 'instagram'
    url             TEXT,               -- URL del post publicado
    title           TEXT,
    description     TEXT,
    hashtags        TEXT,               -- JSON array
    status          TEXT NOT NULL DEFAULT 'pendiente',
    -- Status: pendiente | subido | error
    error_msg       TEXT,
    uploaded_at     TIMESTAMP,
    engagement      TEXT                -- JSON: {views, likes, comments} (futuro)
);

-- =========================================================================
-- PROMPT_VERSIONS: Historial de versiones de prompts
-- =========================================================================
CREATE TABLE IF NOT EXISTS prompt_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    step            TEXT NOT NULL,      -- 'clasificacion' | 'match' | 'caption' | 'upload_metadata'
    version_tag     TEXT,               -- "v3: agregué categoría sus"
    prompt_text     TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT 1,  -- Solo 1 activo por step
    accuracy_avg    REAL,               -- Promedio de accuracy con este prompt
    total_uses      INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- USER_FEEDBACK: Todo el feedback del usuario para mejorar prompts
-- =========================================================================
CREATE TABLE IF NOT EXISTS user_feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcode       TEXT REFERENCES memes(shortcode),
    step            TEXT NOT NULL,      -- 'classify' | 'match' | 'review' | 'batch_review'
    ia_said         TEXT,               -- Lo que la IA respondió
    user_said       TEXT,               -- Lo que el usuario dijo/corrigió
    decision        TEXT,               -- 'accepted' | 'rejected' | 'corrected:X' | 'override:X'
    prompt_version_id INTEGER REFERENCES prompt_versions(id),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- RATE_LIMITS: Tracking de uso de APIs por día
-- =========================================================================
CREATE TABLE IF NOT EXISTS rate_limits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api             TEXT NOT NULL,      -- 'openai' | 'instagram' | 'telegram'
    date            TEXT NOT NULL,      -- YYYY-MM-DD
    requests_count  INTEGER DEFAULT 0,
    tokens_used     INTEGER DEFAULT 0,
    errors_count    INTEGER DEFAULT 0,
    last_request_at TIMESTAMP,
    UNIQUE(api, date)
);

-- =========================================================================
-- PIPELINE_RUNS: Log de ejecuciones del pipeline
-- =========================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,      -- UUID del run
    step            TEXT NOT NULL,      -- Nombre del script/paso
    status          TEXT NOT NULL DEFAULT 'running',  -- 'running' | 'success' | 'error'
    items_processed INTEGER DEFAULT 0,
    items_skipped   INTEGER DEFAULT 0,
    items_error     INTEGER DEFAULT 0,
    duration_s      REAL,
    error_msg       TEXT,
    started_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at     TIMESTAMP
);

-- =========================================================================
-- INDICES para queries frecuentes
-- =========================================================================
CREATE INDEX IF NOT EXISTS idx_memes_status ON memes(status);
CREATE INDEX IF NOT EXISTS idx_memes_profile ON memes(source_profile);
CREATE INDEX IF NOT EXISTS idx_memes_source_type ON memes(source_type);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_rate_limits_api_date ON rate_limits(api, date);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_step ON pipeline_runs(step);
CREATE INDEX IF NOT EXISTS idx_user_feedback_step ON user_feedback(step);
"""


# =============================================================================
# CONEXION
# =============================================================================

def get_db(db_path=None):
    """
    Obtiene conexión singleton a la base de datos.
    Si no existe, la crea e inicializa el schema.
    """
    global _connection
    if _connection is None:
        path = db_path or DB_PATH
        _connection = sqlite3.connect(str(path))
        _connection.row_factory = sqlite3.Row  # Acceso por nombre de columna
        _connection.execute("PRAGMA journal_mode=WAL")  # Better concurrency
        _connection.execute("PRAGMA foreign_keys=ON")
    return _connection


def init_db(db_path=None):
    """
    Inicializa la base de datos: crea tablas e índices si no existen.
    Safe to call multiple times (IF NOT EXISTS).
    """
    db = get_db(db_path)
    db.executescript(SCHEMA)
    db.commit()
    return db


def close_db():
    """Cierra la conexión singleton."""
    global _connection
    if _connection:
        _connection.close()
        _connection = None


@contextmanager
def transaction():
    """
    Context manager para transacciones.
    Commit automático al salir, rollback en excepción.
    
    Uso:
        with transaction() as db:
            db.execute("INSERT ...")
            db.execute("UPDATE ...")
    """
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


# =============================================================================
# HELPERS - MEMES
# =============================================================================

def insert_meme(shortcode, source_profile, source_type='desconocido', **kwargs):
    """Inserta un meme nuevo. Ignora si ya existe (IGNORE)."""
    db = get_db()
    cols = ['shortcode', 'source_profile', 'source_type'] + list(kwargs.keys())
    placeholders = ', '.join(['?'] * len(cols))
    values = [shortcode, source_profile, source_type] + list(kwargs.values())
    db.execute(
        f"INSERT OR IGNORE INTO memes ({', '.join(cols)}) VALUES ({placeholders})",
        values
    )
    db.commit()
    return db.total_changes > 0  # True si se insertó (no duplicado)


def update_meme_status(shortcode, new_status, **extra_fields):
    """Actualiza el status de un meme + campos extra opcionales."""
    db = get_db()
    sets = ['status = ?', 'updated_at = ?']
    values = [new_status, datetime.now().isoformat()]
    
    for key, val in extra_fields.items():
        sets.append(f'{key} = ?')
        values.append(val)
    
    values.append(shortcode)
    db.execute(
        f"UPDATE memes SET {', '.join(sets)} WHERE shortcode = ?",
        values
    )
    db.commit()


def get_memes_by_status(status, limit=None):
    """Obtiene memes filtrados por status."""
    db = get_db()
    query = "SELECT * FROM memes WHERE status = ? ORDER BY scraped_at ASC"
    if limit:
        query += f" LIMIT {limit}"
    return db.execute(query, (status,)).fetchall()


def get_meme(shortcode):
    """Obtiene un meme por shortcode."""
    db = get_db()
    return db.execute("SELECT * FROM memes WHERE shortcode = ?", (shortcode,)).fetchone()


def count_by_status():
    """
    Retorna dict con conteo de memes por status.
    Para el script status.py.
    """
    db = get_db()
    rows = db.execute(
        "SELECT status, COUNT(*) as cnt FROM memes GROUP BY status"
    ).fetchall()
    return {row['status']: row['cnt'] for row in rows}


# =============================================================================
# HELPERS - CLIPS
# =============================================================================

def insert_clip(clip_id, descripcion, filename, categorias=None, **kwargs):
    """Inserta un clip al catálogo."""
    db = get_db()
    cols = ['id', 'descripcion', 'filename']
    values = [clip_id, descripcion, filename]
    if categorias:
        cols.append('categorias')
        values.append(categorias if isinstance(categorias, str) else str(categorias))
    for key, val in kwargs.items():
        cols.append(key)
        values.append(val)
    placeholders = ', '.join(['?'] * len(cols))
    db.execute(
        f"INSERT OR REPLACE INTO clips ({', '.join(cols)}) VALUES ({placeholders})",
        values
    )
    db.commit()


def get_all_clips():
    """Obtiene todos los clips del catálogo."""
    db = get_db()
    return db.execute("SELECT * FROM clips ORDER BY id").fetchall()


# =============================================================================
# HELPERS - MATCHES
# =============================================================================

def insert_match(shortcode, clip_id, accuracy, match_type='manual', **kwargs):
    """Inserta un match meme<->clip."""
    db = get_db()
    cols = ['shortcode', 'clip_id', 'accuracy', 'match_type'] + list(kwargs.keys())
    values = [shortcode, clip_id, accuracy, match_type] + list(kwargs.values())
    placeholders = ', '.join(['?'] * len(cols))
    db.execute(
        f"INSERT INTO matches ({', '.join(cols)}) VALUES ({placeholders})",
        values
    )
    db.commit()


# =============================================================================
# HELPERS - RATE LIMITS
# =============================================================================

def log_api_request(api, tokens=0):
    """Registra un request a una API. Crea/actualiza fila del día."""
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    db.execute("""
        INSERT INTO rate_limits (api, date, requests_count, tokens_used, last_request_at)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(api, date) DO UPDATE SET
            requests_count = requests_count + 1,
            tokens_used = tokens_used + ?,
            last_request_at = ?
    """, (api, today, tokens, datetime.now().isoformat(), tokens, datetime.now().isoformat()))
    db.commit()


def get_daily_usage(api):
    """Obtiene uso del día para una API."""
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')
    row = db.execute(
        "SELECT * FROM rate_limits WHERE api = ? AND date = ?",
        (api, today)
    ).fetchone()
    if row:
        return {'requests': row['requests_count'], 'tokens': row['tokens_used']}
    return {'requests': 0, 'tokens': 0}


# =============================================================================
# HELPERS - PIPELINE RUNS
# =============================================================================

def start_pipeline_run(run_id, step):
    """Registra inicio de un paso del pipeline."""
    db = get_db()
    db.execute(
        "INSERT INTO pipeline_runs (run_id, step, status) VALUES (?, ?, 'running')",
        (run_id, step)
    )
    db.commit()


def finish_pipeline_run(run_id, step, status='success', items_processed=0,
                        items_skipped=0, items_error=0, duration_s=None, error_msg=None):
    """Registra fin de un paso del pipeline."""
    db = get_db()
    db.execute("""
        UPDATE pipeline_runs 
        SET status=?, items_processed=?, items_skipped=?, items_error=?,
            duration_s=?, error_msg=?, finished_at=?
        WHERE run_id=? AND step=?
    """, (status, items_processed, items_skipped, items_error,
          duration_s, error_msg, datetime.now().isoformat(), run_id, step))
    db.commit()


# =============================================================================
# HELPERS - FEEDBACK
# =============================================================================

def log_feedback(shortcode, step, ia_said=None, user_said=None, decision=None, prompt_version_id=None):
    """Registra feedback del usuario."""
    db = get_db()
    db.execute("""
        INSERT INTO user_feedback (shortcode, step, ia_said, user_said, decision, prompt_version_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (shortcode, step, ia_said, user_said, decision, prompt_version_id))
    db.commit()
