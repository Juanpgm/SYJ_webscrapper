# Módulo de Análisis de Percepción de Seguridad (Powered by OpenClaw)

**Versión:** 2.0 (MVP Local)
**Objetivo:** Desplegar un agente autónomo que extraiga, procese y analice texto de medios y redes sociales sobre la seguridad en Santiago de Cali, operando 24/7 sin APIs de pago.

## 1. Arquitectura del MVP

- **Cerebro y Orquestador:** OpenClaw (Instancia Local aislada en Docker/WSL2).
- **Interfaz de Control (Gateway):** Telegram Bot (BotFather). El agente reportará los hallazgos directamente a un chat privado o grupo de Telegram.
- **Motor LLM (Inferencia):** Ollama (Modelo recomendado: `llama3:8b` o `mistral` para mantener el consumo de RAM bajo y latencia rápida).
- **Memoria y Contexto:** \* `SOUL.md`: Define el comportamiento, la toponimia de Cali y el rol analítico del agente.
  - `Memory.md`: Archivo donde OpenClaw guarda el contexto de las alertas diarias.
- **Procesamiento NLP Extra:** Scripts de Python expuestos como _Custom Skills_ para tareas deterministas (ej. `pysentimiento` para análisis de emociones, BERTopic para clústeres).

## 2. Configuración del Agente (SOUL.md)

_OpenClaw debe inicializarse con este prompt base en su archivo de identidad:_

> "Eres 'CaliSecurityBot', un analista de datos autónomo. Tu objetivo es monitorear constantemente la web y redes sociales buscando menciones sobre seguridad, crimen y orden público en Santiago de Cali. Conoces las 22 comunas, el MIO y los barrios principales. Debes filtrar el ruido, extraer incidentes, identificar el sentimiento ciudadano y reportar resúmenes estructurados a través de Telegram dos veces al día, o inmediatamente si detectas un pico anómalo de reportes sobre un mismo sector."

## 3. Skills (Habilidades) Requeridas en OpenClaw

1. **Browser Skill (Navegación Web):** Permite a OpenClaw usar Playwright internamente para navegar por _El País Cali_, _TuBarco_, _Q'hubo_ e instancias de _Nitter_ (para extraer de X sin API).
2. **Cron Skill (Tareas Programadas):** Para que OpenClaw se despierte automáticamente a las 6:00 AM y 6:00 PM a realizar las rondas de extracción.
3. **Python Execution Skill:** Para que el agente pueda correr scripts de limpieza de texto y ejecutar modelos de HuggingFace sobre los datos extraídos.
4. **File System Skill:** Para guardar los resultados estructurados (JSON/CSV) en un directorio local que luego puede ser leído por un Dashboard en Streamlit.

## 4. Pipeline de Ejecución Autónoma

1. **Trigger:** El Cron Skill activa a OpenClaw.
2. **Scraping:** OpenClaw usa el Browser Skill para leer las noticias del día y los últimos comentarios públicos.
3. **Procesamiento:** OpenClaw envía el texto a la instancia local de Ollama para clasificación (NER de barrios, Sentimiento, Tipo de delito).
4. **Almacenamiento:** Guarda el output en formato JSON.
5. **Notificación:** OpenClaw envía un mensaje a Telegram: _"Reporte listo. Hoy se procesaron 450 comentarios. Tema principal: Hurtos en estaciones del MIO (Comuna 3). Sentimiento general: Negativo."_

## 5. Estado de Implementación (2026-03-17)

- [x] Scheduler local base con `APScheduler` en `src/pipeline/scheduler.py`.
- [x] Configuración de horarios MVP (06:00 y 18:00) en `config/scraper_config.yaml`.
- [x] Integración opcional de `Selenium + undetected-chromedriver` en `src/scrapers/selenium_scraper.py`.
- [x] Fallback HTTP-first mantenido en `src/pipeline/orchestrator.py`.
- [x] Entorno aislado inicial con `Dockerfile` y `docker-compose.yml`.
- [x] Guías operativas iniciales en `docs/openclaw_local_setup.md` y `docs/selenium_bot_local.md`.
- [ ] Integración efectiva OpenClaw -> skill wrapper del pipeline Python.
- [ ] Conectores sociales MVP: Nitter, YouTube comentarios, Facebook páginas públicas.
- [ ] Enriquecimiento NLP (barrio/comuna/sentimiento) para salida MVP.

## 6. Comandos de Operación MVP (Actual)

Ejecución única del pipeline:

```bash
python run_scheduler.py --once
```

Modo programado:

```bash
python run_scheduler.py
```

Stack local en Docker (app + Ollama):

```bash
docker compose up -d --build
```
