# Docker Desktop local

Configuracion recomendada para correr el scraper en un PC local con Docker Desktop.

## Requisitos

- Docker Desktop instalado y levantado.
- Si vas a usar Selenium dentro del contenedor, deja en `config/scraper_config.yaml`:
  - `use_selenium_scraper: true`
  - `selenium_headless: true`
- Si vas a usar Ollama dentro de Docker Compose:
  - activa `use_ollama_nlp: true` en `config/scraper_config.yaml`
  - el contenedor `scraper` ya apunta a `http://ollama:11434` via variable de entorno.

## Construir imagen

```powershell
docker compose build scraper
```

## Corrida puntual

Noticias:

```powershell
docker compose run --rm scraper python main.py --fuentes blu_radio_cali --force-reprocess
```

Social YouTube:

```powershell
docker compose run --rm scraper python main.py --include-social --social-only --fuentes youtube_cali --force-reprocess
```

Social Instagram:

```powershell
docker compose run --rm scraper python main.py --include-social --social-only --fuentes instagram_cali --force-reprocess
```

## Scheduler continuo

```powershell
docker compose up -d scraper
```

Ver logs:

```powershell
docker compose logs -f scraper
```

Detener:

```powershell
docker compose stop scraper
```

## Ollama opcional

Levantar solo Ollama:

```powershell
docker compose --profile ollama up -d ollama
```

Descargar un modelo dentro del contenedor:

```powershell
docker exec -it syj_ollama ollama pull llama3.1:8b
```

Levantar scraper y Ollama juntos:

```powershell
docker compose --profile ollama up -d scraper ollama
```

## Datos persistentes

- El proyecto entero se monta como volumen `./:/app`.
- Los resultados quedan en tus carpetas locales:
  - `data/raw_html`
  - `data/parsed_json`
  - `data/checkpoints`
  - `data/failed`

## Notas practicas

- `youtube_transcript_api`, `yt-dlp`, `faster-whisper`, Chromium y ChromeDriver ya quedan dentro de la imagen.
- Instagram y Facebook pueden seguir devolviendo pocos o cero resultados si la superficie publica cambia o exige login.
- Si una fuente social publica se bloquea, usa URLs directas (`post_urls`) en `config/social_sources.yaml`.
