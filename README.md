# SYJ Web Scrapper

Pipeline de scraping multifuente para noticias de seguridad de Cali.

## Ejecutar

```bash
python main.py --fecha-desde 01/01/2026 --fecha-hasta 10/03/2026
```

Opcional filtrar fuentes:

```bash
python main.py --fuentes el_pais_cali blu_radio_cali
```

## Scheduler local (MVP)

Ejecutar una corrida unica:

```bash
python run_scheduler.py --once
```

Incluir conectores sociales MVP:

```bash
python main.py --include-social --social-only --fuentes nitter_cali
```

Ejecutar modo programado (06:00 y 18:00 por defecto):

```bash
python run_scheduler.py
```

## Docker Desktop local

Construir imagen:

```bash
docker compose build scraper
```

Corrida puntual:

```bash
docker compose run --rm scraper python main.py --fuentes blu_radio_cali --force-reprocess
```

Scheduler continuo:

```bash
docker compose up -d scraper
docker compose logs -f scraper
```

Ollama opcional:

```bash
docker compose --profile ollama up -d ollama
docker exec -it syj_ollama ollama pull llama3.1:8b
```

Guia completa:

- `docs/docker_desktop_local.md`

## Comportamiento incremental

- Si el HTML del `article_id` ya existe, no se vuelve a descargar.
- Si el JSON del `article_id` ya existe, no se vuelve a transformar.
- El indice persistente se guarda en `data/checkpoints/article_index.json`.

## Modo Cloudflare

- El proyecto incluye `cloudscraper` para mejorar acceso a paginas con protecciones de Cloudflare.
- Activacion por config en `config/scraper_config.yaml`:
  - `use_cloudflare_scraper: true`
  - `parallel_fetch: true`
  - `parallel_fetch_timeout_seconds: 30`
  - Con `parallel_fetch: true`, el pipeline prueba scrapers HTTP en paralelo y toma el primero que responda.
- Al final de la corrida se registra una comparativa en logs con intentos, exitos y victorias por fetcher.

## Selenium (fallback para sitios dinamicos)

Configurar en `config/scraper_config.yaml`:

- `use_selenium_scraper: true`
- `selenium_timeout_seconds: 30`
- `selenium_headless: true`

Por defecto, Selenium viene desactivado para reducir consumo de recursos.

## NLP minimo

- El pipeline ahora enriquece noticias y posts sociales con:
  - `barrio_detectado`
  - `comuna_detectada`
  - `lugares_mencionados`
  - `sentimiento_score`
  - `sentimiento_label`
  - `tipo_incidente`
- Si activas `use_ollama_nlp: true` en `config/scraper_config.yaml`, intenta mejorar esas etiquetas con Ollama local y hace fallback automatico a reglas si el modelo no responde.

## Fuentes sociales MVP

- Configuración en `config/social_sources.yaml`
- Conectores incluidos:
  - `nitter_cali`
  - `youtube_cali`
  - `facebook_publico_cali`
  - `instagram_cali`
- YouTube ahora intenta guardar texto completo por este orden:
  - transcript/captions oficiales
  - transcripcion por audio con `yt-dlp` + `faster-whisper`
  - descripcion y comentarios visibles como respaldo
- Instagram ahora intenta extraer:
  - publicaciones y reels desde perfiles publicos/hashtags
  - comentarios visibles (usuario, fecha_hora, texto)
  - transcripcion por Whisper cuando detecta URL de video publico
  - si Instagram bloquea listado publico, puedes poblar `post_urls` en `config/social_sources.yaml` para forzar posts/reels puntuales

## Estructura

- `scraper_cali.py`: script principal.
- `src/pipeline/orchestrator.py`: orquestador con rango personalizable.
- `config/sources/`: perfiles por fuente.
- `data/raw_html/`: HTML crudos.
- `data/parsed_json/`: JSON parseados.
