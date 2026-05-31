# Meme Reaction V2 — Documentación Completa

**Última actualización:** 2026-05-31
**Autor:** David Díaz (diazdavidy@johndeere.com)
**Ubicación:** `C:\Users\David\Desktop\Proyectos\drako_edits\drako-edits\automatizaciones\Meme_Reaction_V2\`
**Ejecución:** PowerShell en Windows. Python 3.11+. No usa Docker ni servidores.

---

## 1. QUÉ ES ESTE PROYECTO

Pipeline de automatización para crear videos de reacción a memes (TikTok/Reels/Shorts).
Scrapea memes de Instagram → los clasifica con IA → busca clips de reacción → genera el video final → lo sube.

**Estructura del video final (1080x1920 vertical):**
- Meme (imagen, ~65-70% superior)
- Caption (texto estilo TikTok, opcional, máx 6-8 palabras)
- Clip de reacción (video landscape, ~30% inferior)

---

## 2. ESTRUCTURA DE ARCHIVOS

```
Meme_Reaction_V2/
├── utils/                       # Módulos compartidos (fase 1)
│   ├── __init__.py              # Exports centralizados
│   ├── db.py                    # SQLite: schema + conexión + helpers
│   ├── config.py                # Carga config.json, resuelve ENV:VAR
│   ├── logger.py                # Logging coloreado + rotación + métricas
│   ├── retry.py                 # Decoradores: @with_retry, @retry_openai, @retry_instagram
│   ├── health.py                # 8 checks pre-ejecución
│   ├── rate_limiter.py          # RateLimiter(api) con cuotas en DB
│   └── telegram.py              # send_notification(), notify_error()
│
├── memes_descargados/           # Imágenes descargadas (.jpg/.png/.webp)
├── clips/                       # Clips de reacción (.mp4)
├── audio/                       # Audio extraído de clips (.mp3)
├── logs/                        # Archivos de log rotativos
│
├── config.json                  # Configuración centralizada
├── .env                         # API keys (OPENAI_API_KEY, GOOGLE_API_KEY, TELEGRAM_*)
├── meme_reaction.db             # SQLite: toda la data del pipeline
├── requirements.txt             # Dependencias Python
│
├── 1a_scrape_inicial.py         # Scrape masivo de un perfil nuevo
├── 1b_scrape_nuevos.py          # Scrape incremental multi-perfil
├── 2_download_memes.py          # Descarga + branching (foto/frame/carousel)
├── 2b_preprocess.py             # Auto-crop bordes negros (4 esquinas + detección)
├── batch_review.py              # HTML grid para aprobar/rechazar frames (port 8765)
├── 3_classify_meme.py           # GPT-4o Vision: clasifica memes
├── view_clasificados.py         # QA dashboard de clasificaciones (port 8766)
├── 3b_categorizar_clips.py      # Gemini 2.5 Flash: categoriza clips (video+audio)
├── catalogo_clips.py            # Catálogo visual de clips (port 8767)
├── 4_match_clip.py              # GPT-4o-mini: matchea memes ↔ clips
├── catalogo_matches.py          # Interfaz de decisión meme-clip (port 8768)
├── export_feedback.py           # Exporta feedback para mejorar prompts
├── status.py                    # Vista rápida del estado de todo el pipeline
│
├── DOCS.md                      # ← ESTE ARCHIVO
└── new version upgrades.ipynb   # Notebook de planificación (master plan)
```

---

## 3. BASE DE DATOS (SQLite)

**Archivo:** `meme_reaction.db`
**Modo:** WAL (write-ahead log) + foreign keys ON

### Tablas

| Tabla | PK | Propósito |
|-------|----|-----------|
| `memes` | shortcode (TEXT) | Cada post de IG scrapeado |
| `clasificaciones` | id (AUTO) | Resultado de GPT-4o Vision por meme |
| `clips` | id (TEXT) | Catálogo de clips de reacción |
| `matches` | id (AUTO) | Relación meme↔clip + score + caption |
| `videos_generados` | id (AUTO) | Videos producidos por ffmpeg |
| `uploads` | id (AUTO) | Registro de subidas a redes |
| `prompt_versions` | id (AUTO) | Historial de prompts usados |
| `user_feedback` | id (AUTO) | Todo feedback del usuario |
| `rate_limits` | id (AUTO) | Uso diario de APIs |
| `pipeline_runs` | id (AUTO) | Log de ejecuciones |

### Columnas clave de `memes`

- `shortcode` — ID único del post de Instagram
- `source_profile` — @username de donde se scrapeó
- `source_type` — 'foto' | 'frame' | 'carousel'
- `status` — Estado actual en el pipeline (ver máquina de estados abajo)
- `image_path` — Path al archivo descargado
- `image_hash` — SHA-256 (para cache/dedup)
- Timestamps: scraped_at, downloaded_at, classified_at, matched_at, generated_at, uploaded_at

### Columnas clave de `clips`

- `id` — Formato: `clip_{videoId}_{hash4}` (ej: `clip_SuQ7aLf90QM_96aa`)
- `filename` — Nombre del .mp4 en clips/
- `duracion_s` — Duración en segundos
- `approved` — 1 si fue aprobado en catálogo (0 = pendiente)
- `categorizado_ia_at` — Timestamp de categorización con Gemini
- `mood` — épico|chill|caótico|dramático|cómico|tenso|nostálgico|energético
- `intensidad` — 1-10
- `audio_analisis` — JSON con análisis de audio
- `timing` — JSON con punch_moment, buildup, mejor_rango
- `compatibilidad_meme` — JSON array de narrativas/emociones compatibles

### Columnas clave de `matches`

- `shortcode` — FK a memes
- `clip_id` — FK a clips
- `accuracy` — Score 0-100
- `caption` — Texto del caption elegido
- `match_type` — 'auto' | 'confirmed' | 'manual'
- `match_rank` — Posición (1=mejor match)
- `razon` — Explicación de la IA
- `captions_json` — JSON array con opciones de caption
- `youtube_sugerencias` — JSON array si no hay buen match

---

## 4. MÁQUINA DE ESTADOS (memes.status)

```
por_descargar
  └→ [2_download] → foto→listo_clasificar | frame→pendiente_review | carousel→rechazado

pendiente_review
  └→ [batch_review] → aprobado→listo_clasificar | rechazado (fin)

listo_clasificar
  └→ [3_classify] → valido+!es_video→pendiente_match | else→descartado_ia (fin)

pendiente_match
  └→ [4_match] → ≥90%→por_generar | 40-89%→match_review | <40%→buscar_clip

match_review
  └→ [catalogo_matches --apply] → confirmado→por_generar | skip→pendiente_match

por_generar
  └→ [7_generate] → generado → por_subir → subido (fin)

Estados terminales: rechazado, descartado_ia, subido
```

---

## 5. SCRIPTS — DETALLE FUNCIONAL

### 1a_scrape_inicial.py
- **Input:** @username como argumento
- **Output:** Posts registrados en SQLite como `por_descargar`
- **Tech:** Selenium + Brave (login manual, luego scroll automático)
- **Uso:** `python 1a_scrape_inicial.py --perfil elmello2023 --scrolls 30`

### 1b_scrape_nuevos.py
- **Input:** Lee `perfiles_target` de config.json
- **Output:** Solo posts NUEVOS (no en DB) registrados
- **Tech:** Scroll corto (2-3), compara con SQLite
- **Uso:** `python 1b_scrape_nuevos.py`

### 2_download_memes.py
- **Input:** Memes con status=por_descargar
- **Output:** Archivos en memes_descargados/ + status actualizado
- **Tech:** Instaloader (sin login, 1 query/post) + requests para foto + ffmpeg para frame
- **Branching:** GraphImage→foto→listo_clasificar | GraphVideo→frame→pendiente_review | GraphSidecar→rechazado
- **Protecciones:** Rate limit detection, delay configurable, max por sesión, retry x3
- **Uso:** `python 2_download_memes.py --max 50 --min-likes 5000`

### 2b_preprocess.py
- **Input:** Imágenes en memes_descargados/ con status=listo_clasificar
- **Output:** Imágenes cropeadas (reemplaza in-place)
- **Tech:** Pillow. Detecta bordes negros desde 4 esquinas + análisis de filas
- **Uso:** `python 2b_preprocess.py --margin 6`

### batch_review.py (PORT 8765)
- **Input:** Memes con status=pendiente_review
- **Output:** HTML grid. Botones: SÍ (→listo_clasificar) / RE (→por_descargar) / NO (→rechazado)
- **Tech:** http.server + HTML estático generado
- **Uso:** `python batch_review.py` → abre navegador

### 3_classify_meme.py
- **Input:** Memes con status=listo_clasificar
- **Output:** Fila en `clasificaciones` + status→pendiente_match (o descartado_ia)
- **Tech:** GPT-4o Vision con response_format=json_object
- **Costo:** ~$0.01/meme (imagen low detail + 1500 tokens respuesta)
- **Cache:** Si image_hash ya existe en clasificaciones, skip
- **Uso:** `python 3_classify_meme.py --max 20`

### view_clasificados.py (PORT 8766)
- **Input:** Memes ya clasificados (tabla clasificaciones)
- **Output:** Dashboard QA con 4 botones: OK / RECLASIFICAR / RECHAZAR / 5 NUEVAS
- **Extra:** Click en ideas para marcar favorita (se guarda en user_feedback)
- **Uso:** `python view_clasificados.py`

### descargar_clips.py
- **Input:** URL de YouTube (o archivo batch .txt)
- **Output:** .mp4 en clips/ + .mp3 en audio/ + registro en SQLite
- **Tech:** yt-dlp + ffmpeg (trim, escala a max 1080px ancho)
- **Uso:** `python descargar_clips.py "https://youtube.com/watch?v=XXX" --start 5 --end 12`

### 3b_categorizar_clips.py
- **Input:** Clips con approved=1 y categorizado_ia_at=NULL
- **Output:** Análisis completo (mood, timing, audio, compatibilidad) en SQLite
- **Tech:** Gemini 2.5 Flash (video+audio completo, ~$0.001/clip) con fallback a GPT-4o (5 frames)
- **Fix implementado:** `repair_json()` para manejar JSON malformado de Gemini + retry con temp=0.1
- **Uso:** `python 3b_categorizar_clips.py` (o `--model openai` para fallback)

### catalogo_clips.py (PORT 8767)
- **Input:** Todos los clips en SQLite
- **Output:** Catálogo visual con video preview. Botones: APROBAR / CAMBIOS / RECHAZAR
- **Flag --ia:** Muestra análisis completo de Gemini (mood badge, audio, timing, recs)
- **Extra:** Trim inline, audio swap
- **Uso:** `python catalogo_clips.py --ia`

### 4_match_clip.py
- **Input:** Memes con status=pendiente_match + clips categorizados y aprobados
- **Output:** Top 5 matches en tabla `matches` + meme status actualizado
- **Tech:** GPT-4o-mini (imagen del meme + info texto de todos los clips)
- **Scoring:** ≥90%→por_generar | 40-89%→match_review | <40%→buscar_clip
- **Genera:** Score + razón + 2 captions por combo + sugerencias YouTube si no hay match
- **Costo:** ~$0.008/meme
- **Uso:** `python 4_match_clip.py` (o `--force` para re-matchear)

### catalogo_matches.py (PORT 8768)
- **Input:** Memes con matches generados (status match_review, por_generar, buscar_clip)
- **Output:** HTML meme-por-meme. Click clip + caption → confirmar. Skip → pendiente.
- **Apply:** `python catalogo_matches.py --apply` lee JSON de decisiones y actualiza DB
- **Export:** `python catalogo_matches.py --export` genera JSON para análisis de preferencias
- **Uso:** `python catalogo_matches.py`

### export_feedback.py
- **Input:** Tabla clasificaciones + user_feedback
- **Output:** Texto formateado para copiar/pegar y mejorar prompts
- **Uso:** `python export_feedback.py --only-feedback --clipboard`

### status.py
- **Input:** SQLite completa
- **Output:** Resumen del pipeline (conteos por status, clips, budget, siguiente paso sugerido)
- **Uso:** `python status.py` (o `--detailed` para desglose por perfil, `--telegram` para enviar)

---

## 6. TAXONOMÍA DE CLASIFICACIÓN (55 Tags)

Usada tanto para memes (3_classify_meme.py) como para clips (3b_categorizar_clips.py).

**FORMATO (11):** formato_texto_arriba_imagen_abajo, formato_solo_imagen, formato_texto_overlay, formato_dos_paneles, formato_multi_panel, formato_screenshot_chat, formato_screenshot_tweet, formato_screenshot_comentario, formato_reaccion_con_caption, formato_edit_shitpost, formato_lista_ranking

**HUMOR (10):** humor_absurdo, humor_dark, humor_sexual, humor_cringe, humor_wholesome, humor_ironia, humor_sarcasmo, humor_anti_meme, humor_meta, humor_intelectual

**NARRATIVA (10):** narrativa_plot_twist, narrativa_expectativa_vs_realidad, narrativa_pov, narrativa_nadie_absolutamente_nadie, narrativa_yo_vs_mi_cerebro, narrativa_before_after, narrativa_escalamiento, narrativa_confesion, narrativa_comparacion_falsa, narrativa_literalidad

**EMOCIÓN (8):** reaccion_sorpresa, reaccion_indignacion, reaccion_tristeza_comica, reaccion_panico, reaccion_orgullo_culposo, reaccion_nostalgia, reaccion_relatable, reaccion_flexeo

**TEMÁTICA (14):** tema_relaciones, tema_familia, tema_trabajo, tema_escuela, tema_gaming, tema_internet_cultura, tema_dinero, tema_comida, tema_animales, tema_mexico_latam, tema_musica, tema_deporte, tema_politica_light, tema_existencial

**TONO (4):** tono_suave, tono_medio, tono_fuerte, tono_NSFW_light

---

## 7. APIs Y COSTOS

| API | Modelo | Uso | Costo aprox |
|-----|--------|-----|-------------|
| OpenAI | GPT-4o | Clasificación de memes | ~$0.01/meme |
| OpenAI | GPT-4o-mini | Matching meme↔clip | ~$0.008/meme |
| Google | Gemini 2.5 Flash | Categorización de clips | ~$0.001/clip |
| Instagram | Instaloader (sin login) | Query tipo+likes | Gratis (rate limited) |
| YouTube | yt-dlp | Descarga clips | Gratis |

**Budget OpenAI:** $5 total. ~$4.80 restante (2026-05-31).
**Gemini:** Billing habilitado. 1K RPM, 1M TPM, 10K RPD.

---

## 8. CONFIGURACIÓN

### config.json (extracto de keys importantes)
```json
{
  "perfiles_target": ["elmello2023"],
  "clasificacion": { "modelo": "gpt-4o", "max_por_sesion": 20 },
  "match": { "modelo": "gpt-4o-mini", "auto_accept_threshold": 90, "auto_skip_threshold": 40 },
  "video": { "width": 1080, "height": 1920, "meme_max_ratio": 0.70 },
  "rate_limits": { "openai": { "max_requests_per_day": 500, "max_tokens_per_day": 100000 } }
}
```

### .env (variables requeridas)
```
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AI...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

---

## 9. PUERTOS HTTP

| Puerto | Script | Función |
|--------|--------|---------|
| 8765 | batch_review.py | Review de frames |
| 8766 | view_clasificados.py | QA de clasificaciones |
| 8767 | catalogo_clips.py | Catálogo de clips |
| 8768 | catalogo_matches.py | Decisión de matches |

Todos son `http://127.0.0.1:{port}` con `http.server`. Se abren en el navegador automáticamente. Ctrl+C para cerrar.

---

## 10. FLUJO COMPLETO DE EJECUCIÓN

```bash
# 1. Scrape (solo primera vez por perfil)
python 1a_scrape_inicial.py --perfil elmello2023 --scrolls 20

# 1b. Scrape incremental (ejecuciones regulares)
python 1b_scrape_nuevos.py

# 2. Descarga
python 2_download_memes.py

# 2b. Preprocessing (crop bordes)
python 2b_preprocess.py

# 2c. Review manual de frames
python batch_review.py

# 3. Clasificar memes con IA
python 3_classify_meme.py

# 3b. Categorizar clips (si hay nuevos)
python 3b_categorizar_clips.py

# 4. Matching meme↔clip
python 4_match_clip.py

# 4b. Revisión de matches
python catalogo_matches.py
python catalogo_matches.py --apply

# 7. Generar video (PENDIENTE)
python 7_generate_video.py

# 9. Upload (PENDIENTE)
python 9_upload_social.py

# En cualquier momento:
python status.py
```

---

## 11. PATRONES DE CÓDIGO OBLIGATORIOS

### HTML/JS en Python (NUNCA triple-quotes para JS)
```python
# CORRECTO:
html_parts.append('function foo(){')
html_parts.append('  var x = document.querySelector(\'.class[data-id="'+id+'"]\');')
html_parts.append('}')

# INCORRECTO (ROMPE):
js = """function foo(){...}"""  # ← NUNCA
```

### OpenAI JSON Response
```python
response_format={"type": "json_object"}  # SIEMPRE para JSON
```

### Gemini JSON Cleanup
```python
result = repair_json(response.text)  # Función en 3b_categorizar_clips.py
```

### SQLite Pattern
```python
from utils.db import init_db, get_db
init_db()  # Al inicio del script
db = get_db()  # Singleton, row_factory=sqlite3.Row
```

---

## 12. SCRIPTS PENDIENTES (NO CONSTRUIDOS AÚN)

| Script | Función | Dependencias |
|--------|---------|--------------|
| `7_generate_video.py` | Ensambla meme+caption+clip con ffmpeg/moviepy | matches confirmados |
| `9_upload_social.py` | Sube a TikTok/IG/YouTube con metadata IA | videos generados |
| `clip_finder_manual.py` | Sugiere búsquedas YouTube para memes sin clip | memes en buscar_clip |

---

## 13. CONTEOS ACTUALES (2026-05-31)

```
Memes totales:          372
Pendiente match:        12
Clips totales:          22
Clips aprobados:        22
Clips categorizados:    17 (5 fallaron JSON, pendientes retry)
Videos generados:       0
Subidos:                0
```

---

## 14. DECISIONES DE DISEÑO

1. **SQLite > JSON** — Una sola fuente de verdad, queries, índices, FKs
2. **Scripts independientes** — Cada uno lee su cola de SQLite. Puedes correr cualquiera en cualquier orden.
3. **Branching** — Fotos van directo a IA. Frames pasan por review humano primero.
4. **Clips reutilizables, memes one-time** — Un clip puede ir en múltiples videos. Un meme solo se usa una vez.
5. **Gemini para video, OpenAI para texto/imagen** — Gemini es 35x más barato para video+audio.
6. **HTML interfaces** — Simples http.server, sin frameworks, dark theme, funcional.
7. **Feedback loop** — Todo lo que el usuario decide se guarda para mejorar prompts.

---

## 15. TROUBLESHOOTING COMÚN

| Error | Causa | Fix |
|-------|-------|-----|
| `FOREIGN KEY constraint failed` | clip_id no existe en clips | Validar IDs antes de INSERT |
| `404 models/gemini-2.0-flash` | Modelo deprecado | Usar `gemini-2.5-flash` |
| `Unterminated string` en JSON | Gemini devuelve JSON malformado | `repair_json()` lo arregla |
| `429 Rate Limit` en Instagram | Demasiadas queries | Esperar 30min o usar delay más largo |
| `querySelector` roto en HTML | Comillas mal escapadas en JS | Usar single-quotes para selector |
| GPT devuelve `clip_4` en vez de ID real | Formato del prompt confunde | Presentar IDs como `[clip_xxx]` sin numeración |
