# SYJ WebScrapper

Pipeline de scraping multifuente para monitoreo de noticias y redes sociales de **seguridad ciudadana en Cali**. Incluye API REST (FastAPI), pipeline de radio en vivo con transcripción automática, y soporte para fuentes sociales (YouTube, Instagram, Twitter/Nitter, Facebook).

---

## Tabla de contenidos

- [Arquitectura](#arquitectura)
- [Fuentes configuradas](#fuentes-configuradas)
- [Instalación](#instalación)
- [Levantar la API](#levantar-la-api)
- [API REST — Referencia completa](#api-rest--referencia-completa)
  - [Sistema](#sistema)
  - [Fuentes](#fuentes)
  - [Scraping (jobs en background)](#scraping-jobs-en-background)
  - [Jobs](#jobs)
  - [Artículos](#artículos)
  - [Radio](#radio)
  - [Transcripción YouTube](#transcripción-youtube)
  - [Autenticación YouTube](#autenticación-youtube)
- [CLI — Ejecución directa](#cli--ejecución-directa)
- [Scheduler](#scheduler)
- [Docker](#docker)
- [Configuración](#configuración)
- [Pipeline de datos](#pipeline-de-datos)
- [NLP mínimo](#nlp-mínimo)
- [Notas de desarrollo](#notas-de-desarrollo)

---

## Arquitectura

```
SYJ_webScrapper/
├── api/                        # FastAPI REST
│   ├── main.py                 # App + endpoints sistema/fuentes/scraping/jobs/artículos
│   ├── models.py               # Pydantic request models
│   ├── jobs.py                 # Job store en memoria (UUID, estado, stats)
│   ├── pipeline.py             # Adapter entre API y orquestador
│   ├── radio.py                # Router /radio/* (SSE, control emisoras)
│   ├── transcribe.py           # Router /transcribe/youtube
│   └── auth.py                 # Router /auth/youtube/* (cookies, PO token)
├── src/
│   ├── pipeline/
│   │   └── orchestrator.py     # Orquestador principal (paralelismo, etapas)
│   ├── scrapers/               # Fetchers HTTP (requests, cloudscraper, selenium)
│   ├── parsers/                # Parsers por fuente
│   ├── social/                 # Conectores sociales (YouTube, Instagram, Nitter)
│   ├── radio/
│   │   ├── manager.py          # Manager de workers de radio
│   │   └── worker.py           # Worker por emisora (descarga + Whisper)
│   ├── auth/
│   │   ├── youtube_auth.py     # PO Token + cookies yt-dlp
│   │   └── browser_login.py    # Login OAuth via Chrome
│   └── nlp/                    # Enriquecimiento NLP (barrio, sentimiento, tipo incidente)
├── config/
│   ├── scraper_config.yaml     # Config global (scrapers, NLP, paths, paralelismo)
│   ├── sources/                # Un YAML por fuente de noticias
│   │   ├── el_pais_cali.yaml
│   │   ├── qhubo_cali.yaml
│   │   ├── diario_occidente_valle.yaml
│   │   ├── el_tiempo_nacional.yaml
│   │   └── blu_radio_cali.yaml
│   ├── social_sources.yaml     # Fuentes sociales (YouTube, Instagram, Nitter, Facebook)
│   └── radio_sources.yaml      # Emisoras de radio con URLs de YouTube
├── data/
│   ├── raw_html/               # HTML crudos descargados
│   ├── parsed_json/            # JSON parseados por fuente (<source_id>.json)
│   ├── radio/                  # Segmentos transcritos de radio
│   ├── failed/                 # Artículos que fallaron al parsear
│   └── checkpoints/            # Índices persistentes
├── main.py                     # Punto de entrada CLI
├── run_api.py                  # Punto de entrada API
├── run_scheduler.py            # Scheduler automático (APScheduler)
├── requirements.txt
└── docker-compose.yml
```

---

## Fuentes configuradas

### Noticias (`GET /sources`)

| ID | Nombre |
|----|--------|
| `el_pais_cali` | El País Cali |
| `qhubo_cali` | Q'Hubo Cali |
| `diario_occidente_valle` | Diario Occidente |
| `el_tiempo_nacional` | El Tiempo |
| `blu_radio_cali` | Blu Radio Cali |

### Sociales (`GET /social-sources`)

| ID | Plataforma |
|----|-----------|
| `nitter_cali` | Twitter/Nitter |
| `youtube_cali` | YouTube |
| `facebook_publico_cali` | Facebook |
| `instagram_cali` | Instagram |

### Radio (`GET /radio/stations`)

Configuradas en `config/radio_sources.yaml`. Cada emisora tiene una URL de stream de YouTube.

---

## Instalación

```bash
# Clonar e instalar dependencias
pip install -r requirements.txt

# Node.js requerido para PO Token de YouTube
npm install -g youtube-po-token-generator
```

Opcionalmente instalar ChromeDriver para Selenium (fallback en sitios dinámicos) y para el login de YouTube via browser.

---

## Levantar la API

```bash
python run_api.py --host 127.0.0.1 --port 8000 --reload
```

Una vez levantada:

- **Swagger UI (interactivo):** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json

---

## API REST — Referencia completa

> Todos los endpoints devuelven JSON. Los jobs de scraping son asíncronos: disparan el proceso en background y retornan un `job_id` para hacer polling.

---

### Sistema

#### `GET /`
Health check. Retorna versión, conteo de fuentes y configuración activa.

**No requiere parámetros.**

---

#### `GET /stats`
Estadísticas de almacenamiento: artículos por fuente y conteo de jobs por estado.

**No requiere parámetros.**

---

### Fuentes

#### `GET /sources`
Lista todas las fuentes de noticias configuradas. Usar para obtener `source_id` válidos.

**No requiere parámetros.**

---

#### `GET /sources/{source_id}`
Retorna la configuración completa de una fuente de noticias.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `source_id` | path | Sí | ID de la fuente. Obtenerlo de `GET /sources` → campo `id`. Ej: `el_pais_cali` |

---

#### `GET /social-sources`
Lista todas las fuentes sociales configuradas. Usar para obtener `social_id` válidos.

**No requiere parámetros.**

---

### Scraping (jobs en background)

Los tres endpoints de scraping retornan inmediatamente con un `job_id`. El proceso corre en background. Consultar estado con `GET /jobs/{job_id}`.

#### `POST /scrape/run`
Ejecuta el pipeline completo.

**Body JSON:**

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `fecha_desde` | `string\|null` | `null` | Fecha inicio, formato `DD/MM/YYYY`. Si se omite, usa la configurada en `scraper_config.yaml`. Ej: `01/03/2026` |
| `fecha_hasta` | `string\|null` | `null` | Fecha fin, formato `DD/MM/YYYY`. Si se omite, usa fecha actual. Ej: `27/03/2026` |
| `fuentes` | `list[string]\|null` | `null` (todas) | IDs de fuentes a incluir. Obtener de `GET /sources`. Ej: `["el_pais_cali", "qhubo_cali"]` |
| `force_reprocess` | `bool` | `false` | Re-descarga y re-parsea artículos ya existentes en disco |
| `html_only` | `bool` | `false` | Solo descarga HTML sin parsear. Útil para depuración |
| `include_social` | `bool` | `false` | Ejecuta también conectores sociales además de noticias |
| `social_only` | `bool` | `false` | Ejecuta solo conectores sociales, omite fuentes de noticias |

```json
// Ejemplo mínimo
{}

// Ejemplo con filtros
{
  "fecha_desde": "01/03/2026",
  "fecha_hasta": "27/03/2026",
  "fuentes": ["el_pais_cali", "qhubo_cali"]
}
```

---

#### `POST /scrape/source/{source_id}`
Scraping de una sola fuente.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `source_id` | path | Sí | ID de la fuente. Obtener de `GET /sources`. Ej: `el_pais_cali` |

**Body JSON:**

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `fecha_desde` | `string\|null` | `null` | Fecha inicio `DD/MM/YYYY` |
| `fecha_hasta` | `string\|null` | `null` | Fecha fin `DD/MM/YYYY` |
| `force_reprocess` | `bool` | `false` | Reprocesar artículos existentes |
| `html_only` | `bool` | `false` | Solo descargar HTML |

---

#### `POST /scrape/social`
Scraping solo de fuentes sociales.

**Body JSON:**

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `fecha_desde` | `string\|null` | `null` | Fecha inicio `DD/MM/YYYY` |
| `fecha_hasta` | `string\|null` | `null` | Fecha fin `DD/MM/YYYY` |
| `social_ids` | `list[string]\|null` | `null` (todos) | IDs de conectores. Obtener de `GET /social-sources`. Si se omite, ejecuta todos. |
| `force_reprocess` | `bool` | `false` | Reprocesar entradas existentes |

---

### Jobs

#### `GET /jobs`
Lista todos los jobs registrados en memoria (se pierde al reiniciar la API).

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `status` | query | No | Filtrar por estado: `pending`, `running`, `done`, `failed`. Si se omite, retorna todos. |

---

#### `GET /jobs/{job_id}`
Estado y estadísticas de un job específico.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `job_id` | path | Sí | UUID del job, retornado al disparar el scraping. Ej: `3fa85f64-5717-4562-b3fc-2c963f66afa6` |

---

### Artículos

#### `GET /articles`
Lista artículos almacenados en disco con filtros y paginación.

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `source` | query | `null` | ID de fuente. Si se omite, agrega todas las fuentes. Obtener de `GET /sources`. |
| `fecha_desde` | query | `null` | Filtrar publicados desde esta fecha, formato `DD/MM/YYYY`. Ej: `01/03/2026` |
| `fecha_hasta` | query | `null` | Filtrar publicados hasta esta fecha, formato `DD/MM/YYYY`. Ej: `27/03/2026` |
| `limit` | query | `50` | Artículos por página. Rango: 1–500. |
| `offset` | query | `0` | Artículos a saltar. Para página 2 con limit=50, usar `offset=50`. |

---

#### `GET /articles/{article_id}`
Retorna un artículo específico por su número de ID y fuente.

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `article_id` | path | Sí | Número entero `id_noticia` del artículo. Obtener del campo `id_noticia` en `GET /articles`. |
| `source` | query | Sí | ID de la fuente a la que pertenece el artículo. Requerido. |

---

### Radio

#### `GET /radio/status`
Estado de todos los workers de radio: `offline`, `watching`, `transcribing`, etc.

#### `GET /radio/stations`
Lista de emisoras configuradas en `config/radio_sources.yaml`. Usar para obtener `station_id` válidos.

#### `GET /radio/stats`
Conteo de segmentos transcritos por emisora.

#### `POST /radio/start`
Inicia todas las emisoras con `enabled: true` en la configuración.

#### `POST /radio/stop`
Detiene todos los workers activos.

#### `POST /radio/stations/{station_id}/start`

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `station_id` | path | Sí | ID de la emisora. Obtener de `GET /radio/stations`. Ej: `tropicana_cali` |

#### `POST /radio/stations/{station_id}/stop`

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `station_id` | path | Sí | ID de la emisora. Obtener de `GET /radio/stations`. |

#### `GET /radio/stations/{station_id}/status`

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `station_id` | path | Sí | ID de la emisora. Obtener de `GET /radio/stations`. |

#### `GET /radio/transcriptions`
Transcripciones recientes de todas las emisoras.

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `limit` | query | `50` | Máximo de entradas. Rango: 1–500. |
| `since` | query | `null` | Solo retornar entradas posteriores a este timestamp ISO 8601. Formato: `YYYY-MM-DDTHH:MM:SS`. Ej: `2026-03-27T10:00:00`. Útil para polling incremental. |

#### `GET /radio/transcriptions/{station_id}`

| Parámetro | Tipo | Default | Descripción |
|-----------|------|---------|-------------|
| `station_id` | path | — | ID de emisora. Obtener de `GET /radio/stations`. |
| `limit` | query | `50` | Máximo de entradas. Rango: 1–500. |
| `since` | query | `null` | Timestamp ISO 8601 mínimo. Ej: `2026-03-27T10:00:00` |

#### `GET /radio/stream` y `GET /radio/stream/{station_id}`
**Server-Sent Events** — stream de transcripciones en tiempo real. No usa polling; mantiene conexión HTTP abierta.

```js
// Ejemplo de consumo en JavaScript
const es = new EventSource('http://localhost:8000/radio/stream');
es.onmessage = e => console.log(JSON.parse(e.data));
// Cada evento: { station_id, station_name, timestamp, chunk_start, chunk_end, text, confidence }
```

---

### Transcripción YouTube

#### `POST /transcribe/youtube`
Descarga audio de cualquier URL de YouTube y transcribe con faster-whisper.

**Body JSON:**

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `url` | `string` | — | **Requerido.** URL completa del video. Acepta videos, Shorts y streams en vivo. Ej: `https://www.youtube.com/watch?v=X54nbYSoH-A` |
| `model` | `string` | `"small"` | Modelo Whisper: `tiny` → `base` → `small` → `medium` → `large-v3`. Mayor = más preciso y más lento. En CPU usar `tiny` o `base` para velocidad. |
| `language` | `string` | `"es"` | Código ISO 639-1 del idioma. Ej: `es`, `en`, `pt`. Mejora precisión vs auto-detección. |
| `device` | `string` | `"cpu"` | `cpu` (siempre disponible), `cuda` (requiere GPU NVIDIA), `auto` (elige GPU si existe). |
| `compute_type` | `string` | `"int8"` | Precisión: `int8` (CPU, rápido), `float16` (GPU, balance), `float32` (máxima precisión). |
| `vad_filter` | `bool` | `true` | Activa Voice Activity Detection. Filtra música y silencio. Recomendado `true` para radio. |
| `beam_size` | `int` | `2` | Beam search size (1–10). `1` = greedy (más rápido). `2`–`5` = uso práctico. |
| `force_refresh_token` | `bool` | `false` | Forzar regeneración del PO Token. Usar si la descarga falla por auth. |

**Retorna:** transcripción completa, segmentos con timestamps, metadatos del video y métricas detalladas (tiempo por fase, memoria RSS, CPU).

---

### Autenticación YouTube

#### `GET /auth/youtube/status`
Estado actual: si hay cookies cargadas y si el PO Token está activo.

#### `POST /auth/youtube/cookies`
Sube `cookies.txt` exportado del browser para autenticar yt-dlp.

**Cómo exportar cookies:**
- **Chrome/Edge:** Instalar extensión "Get cookies.txt LOCALLY" → abrir youtube.com logueado → Export → subir aquí.
- **Firefox:** Extensión "cookies.txt" → youtube.com → descargar → subir aquí.

El archivo debe estar en formato Netscape (primera línea: `# Netscape HTTP Cookie File`).

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| `file` | form-data | Sí | Archivo `cookies.txt` en formato Netscape. |

#### `GET /auth/youtube/cookies`
Info sobre las cookies actualmente cargadas.

#### `DELETE /auth/youtube/cookies`
Elimina el archivo de cookies guardado.

#### `POST /auth/youtube/login`
Abre Chrome para login OAuth de Google/YouTube. Las cookies se capturan automáticamente al completar el login.

**Body JSON:**

| Campo | Tipo | Default | Descripción |
|-------|------|---------|-------------|
| `timeout_seconds` | `int` | `300` | Segundos máximos para completar el login (30–600). |

Consultar estado con `GET /auth/youtube/login/status`.

#### `GET /auth/youtube/login/status`
Estados posibles: `idle`, `waiting_login`, `capturing`, `done`, `error`.

#### `POST /auth/youtube/po-token`
Genera un nuevo PO Token (Proof of Origin) usando Node.js. Se renueva automáticamente cada 5 minutos. Requiere `npm install -g youtube-po-token-generator`.

---

## CLI — Ejecución directa

```bash
# Rango de fechas específico
python main.py --fecha-desde 01/01/2026 --fecha-hasta 10/03/2026

# Solo fuentes específicas
python main.py --fuentes el_pais_cali blu_radio_cali

# Solo redes sociales
python main.py --include-social --social-only

# Forzar reprocesamiento
python main.py --force-reprocess
```

---

## Scheduler

```bash
# Corrida única y sale
python run_scheduler.py --once

# Modo programado (06:00 y 18:00 por defecto)
python run_scheduler.py
```

---

## Docker

```bash
# Construir imagen
docker compose build scraper

# Corrida puntual
docker compose run --rm scraper python main.py --fuentes blu_radio_cali --force-reprocess

# Scheduler continuo
docker compose up -d scraper
docker compose logs -f scraper

# Ollama (NLP opcional)
docker compose --profile ollama up -d ollama
docker exec -it syj_ollama ollama pull llama3.1:8b
```

Ver guía completa en `docs/docker_desktop_local.md`.

---

## Configuración

### `config/scraper_config.yaml`

```yaml
parallel_fetch: true              # Prueba scrapers HTTP en paralelo
parallel_fetch_timeout_seconds: 30
use_cloudflare_scraper: true      # Bypass Cloudflare con cloudscraper
use_selenium_scraper: false       # Selenium para JS pesado (más lento)
selenium_headless: true
selenium_timeout_seconds: 30
max_parallel_articles: 24         # Workers en thread pool
use_ollama_nlp: false             # NLP mejorado con Ollama local
```

### `config/sources/<source_id>.yaml`

Un archivo por fuente. Contiene `id`, `name`, `base_url`, `listing_urls`, selectores CSS para parseo, etc.

### `config/social_sources.yaml`

Configuración de conectores sociales: plataforma, handles/URLs, opciones de scraping.

### `config/radio_sources.yaml`

Emisoras con URL de stream YouTube, idioma, y flag `enabled`.

---

## Pipeline de datos

1. **Discovery** — Google Discovery API + listing URLs para encontrar artículos del rango de fechas.
2. **Fetch** — Descarga HTML en paralelo (requests → cloudscraper → selenium según config).
3. **Cache** — HTML se guarda en `data/raw_html/`. Si ya existe, no se vuelve a descargar.
4. **Parse** — Extrae título, cuerpo, fecha, autor con selectores CSS por fuente.
5. **NLP** — Enriquece con barrio, comuna, sentimiento, tipo de incidente.
6. **Store** — JSON por fuente en `data/parsed_json/<source_id>.json`.

**Checkpoint incremental:** `data/checkpoints/article_index.json` evita reprocesar artículos ya guardados.

---

## NLP mínimo

El pipeline enriquece cada artículo/post con:

| Campo | Descripción |
|-------|-------------|
| `barrio_detectado` | Barrio de Cali mencionado en el texto |
| `comuna_detectada` | Comuna correspondiente al barrio |
| `lugares_mencionados` | Lista de lugares geográficos detectados |
| `sentimiento_score` | Score numérico de sentimiento |
| `sentimiento_label` | `positivo`, `negativo`, `neutro` |
| `tipo_incidente` | Categoría del hecho (hurto, homicidio, etc.) |

Con `use_ollama_nlp: true` usa Ollama local (modelo `llama3.1:8b`) para mejorar la extracción, con fallback automático a reglas si el modelo no responde.

---

## Notas de desarrollo

- **Stack:** Python 3.12, FastAPI 0.115+, Pydantic v2, faster-whisper 1.2, yt-dlp, APScheduler.
- **Jobs:** En memoria (se pierden al reiniciar). Sin persistencia de jobs entre reinicios de la API.
- **Radio workers:** Cada emisora corre en un hilo daemon. El manager controla inicio/stop.
- **PO Token:** Se cachea y renueva cada 5 min automáticamente. Requiere Node.js + `youtube-po-token-generator`.
- **Cookies YouTube:** Se guardan en disco en `data/auth/youtube_cookies.txt`.
- **Swagger UI:** Para probar endpoints con body, usar el botón "Try it out" en `/docs`. Los ejemplos de cada campo aparecen precargados.
- **SSE (radio/stream):** No soportado en Swagger UI. Usar `curl` o EventSource en JS.

```bash
# Probar SSE con curl
curl -N http://localhost:8000/radio/stream
```
