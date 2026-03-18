# OpenClaw Local Setup (Docker + Ollama)

Esta guia deja OpenClaw como ruta principal y mantiene este repo como motor de scraping y procesamiento.

## 1) Prerrequisitos

- Docker Desktop activo
- Proyecto en `A:\programing_workspace\SYJ_webScrapper`
- Recursos locales recomendados para Ollama:
  - 16 GB RAM (minimo util: 8 GB)
  - 4 vCPU

## 2) Levantar stack base

Desde la raiz del proyecto:

```powershell
docker compose up -d --build
```

Validar estado:

```powershell
docker compose ps
```

## 3) Inicializar Ollama

Descargar modelo liviano en el contenedor Ollama:

```powershell
docker exec -it syj_ollama ollama pull llama3:8b
```

Probar inferencia:

```powershell
docker exec -it syj_ollama ollama run llama3:8b "resume: inseguridad en cali"
```

## 4) Instalar OpenClaw (host o contenedor dedicado)

Si usas Node en host:

```powershell
npm install -g openclaw
openclaw --help
```

Si falla instalacion global, usa ejecucion directa:

```powershell
npx openclaw --help
```

## 5) Configurar OpenClaw para LLM local

En el onboarding de OpenClaw:

- Provider: OpenAI-compatible o Local
- Base URL: `http://localhost:11434/v1`
- Model: `llama3:8b`
- API key: valor dummy si la UI lo exige (por ejemplo `ollama-local`)

## 6) Operacion diaria recomendada

- Rondas: 06:00 y 18:00 (America/Bogota)
- Flujo: OpenClaw trigger -> comando Python en este repo -> resultado local en `reports/`
- Fallback: si OpenClaw falla, mantener `python run_scheduler.py` activo

## 7) Comandos utiles

Ejecucion unica de scraping:

```powershell
python run_scheduler.py --once
```

Ejecucion desde skill/comando de OpenClaw:

```powershell
python -m src.integrations.openclaw_entrypoint --fuentes el_pais_cali blu_radio_cali
```

Ejecutar solo sociales desde OpenClaw:

```powershell
python -m src.integrations.openclaw_entrypoint --include-social --social-only --fuentes nitter_cali
```

Ejecucion programada:

```powershell
python run_scheduler.py
```

## 8) Troubleshooting rapido

- Si Selenium no inicia en Docker:
  - verificar que `chromium` y `chromium-driver` esten instalados en la imagen
- Si Ollama no responde:
  - revisar `docker logs syj_ollama`
- Si OpenClaw no detecta el modelo:
  - confirmar URL `http://localhost:11434/v1`
  - verificar modelo descargado con `ollama list`
