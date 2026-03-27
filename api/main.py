"""
SYJ WebScrapper — FastAPI REST API
Ejecuta los scrapers a través de endpoints HTTP con tracking de jobs en background.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse

from api.jobs import Job, JobStatus, job_store
from api.models import (
    ArticleFilters,
    ScrapeRunRequest,
    ScrapeSourceRequest,
    ScrapeSocialRequest,
)
from api.pipeline import ROOT, get_news_sources, get_social_sources, run_pipeline
from api.radio import router as radio_router
from api.transcribe import router as transcribe_router
from api.auth import router as auth_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scraper.api")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SYJ WebScrapper API",
    description="API REST para scrapers de noticias, redes sociales y radio en vivo via YouTube.",
    version="1.1.0",  # radio pipeline añadido
    docs_url="/docs",
    redoc_url="/redoc",
)

app.include_router(radio_router)
app.include_router(transcribe_router)
app.include_router(auth_router)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_app_cfg() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "config" / "scraper_config.yaml").read_text(encoding="utf-8"))


def _run_job(job: Job, **pipeline_kwargs: Any) -> None:
    job.status = JobStatus.RUNNING
    job.started_at = datetime.now()
    job_store.update(job)
    try:
        stats = run_pipeline(log=log, **pipeline_kwargs)
        job.stats = stats
        job.status = JobStatus.DONE
    except Exception as exc:
        log.exception("Job %s fallido: %s", job.id, exc)
        job.error = str(exc)
        job.status = JobStatus.FAILED
    finally:
        job.finished_at = datetime.now()
        job_store.update(job)


def _parse_date_filter(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d/%m/%Y")
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Formato de fecha inválido: '{value}'. Use DD/MM/YYYY.")


def _load_articles_for_source(source_id: str) -> list[dict[str, Any]]:
    cfg = _load_app_cfg()
    parsed_dir = Path(cfg["paths"]["parsed_json_dir"])
    json_path = parsed_dir / f"{source_id}.json"
    if not json_path.exists():
        return []
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Endpoints — Sistema
# ---------------------------------------------------------------------------

@app.get("/", tags=["sistema"], summary="Health check")
def health_check() -> dict[str, Any]:
    cfg = _load_app_cfg()
    sources = get_news_sources()
    social = get_social_sources()
    return {
        "status": "ok",
        "version": "1.1.0",
        "timestamp": datetime.now().isoformat(),
        "news_sources_count": len(sources),
        "social_sources_count": len(social),
        "config": {
            "parallel_fetch": cfg.get("parallel_fetch", True),
            "use_selenium": cfg.get("use_selenium_scraper", False),
            "use_cloudflare": cfg.get("use_cloudflare_scraper", True),
            "use_ollama_nlp": cfg.get("use_ollama_nlp", False),
            "max_parallel_articles": cfg.get("max_parallel_articles", 24),
        },
    }


# ---------------------------------------------------------------------------
# Endpoints — Fuentes
# ---------------------------------------------------------------------------

@app.get("/sources", tags=["fuentes"], summary="Listar fuentes de noticias")
def list_sources() -> list[dict[str, Any]]:
    """Retorna todas las fuentes de noticias configuradas en config/sources/."""
    sources = get_news_sources()
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "priority": s.get("priority"),
            "base_url": s.get("base_url"),
            "listing_urls": s.get("listing_urls", []),
        }
        for s in sources
    ]


@app.get("/sources/{source_id}", tags=["fuentes"], summary="Detalle de una fuente")
def get_source(
    source_id: Annotated[
        str,
        Path(
            description="ID de la fuente de noticias. Obtén los IDs disponibles con `GET /sources` (campo `id`).",
            example="el_pais_cali",
        ),
    ],
) -> dict[str, Any]:
    """Retorna la configuración completa de una fuente de noticias por ID."""
    sources = get_news_sources()
    match = next((s for s in sources if s["id"].lower() == source_id.lower()), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Fuente '{source_id}' no encontrada.")
    return match


@app.get("/social-sources", tags=["fuentes"], summary="Listar fuentes sociales")
def list_social_sources() -> list[dict[str, Any]]:
    """Retorna todas las fuentes de redes sociales configuradas en config/social_sources.yaml."""
    social = get_social_sources()
    return [
        {
            "id": s.get("id"),
            "platform": s.get("platform"),
            "enabled": s.get("enabled", True),
        }
        for s in social
    ]


# ---------------------------------------------------------------------------
# Endpoints — Scraping (disparan jobs en background)
# ---------------------------------------------------------------------------

@app.post("/scrape/run", tags=["scraping"], summary="Ejecutar pipeline completo")
def scrape_run(request: ScrapeRunRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """
    Ejecuta el pipeline completo de scraping en background.
    Retorna un job_id para consultar el estado.
    """
    _parse_date_filter(request.fecha_desde)
    _parse_date_filter(request.fecha_hasta)

    params = request.model_dump()
    job = job_store.create(kind="full_pipeline", params=params)

    background_tasks.add_task(
        _run_job,
        job,
        fecha_desde=request.fecha_desde,
        fecha_hasta=request.fecha_hasta,
        fuentes=request.fuentes,
        force_reprocess=request.force_reprocess,
        html_only=request.html_only,
        include_social=request.include_social,
        social_only=request.social_only,
    )

    return {"job_id": job.id, "status": job.status, "message": "Pipeline iniciado en background."}


@app.post("/scrape/source/{source_id}", tags=["scraping"], summary="Scrape de una fuente específica")
def scrape_source(
    source_id: Annotated[
        str,
        Path(
            description="ID de la fuente a scrapear. Obtén los IDs disponibles con `GET /sources` (campo `id`).",
            example="el_pais_cali",
        ),
    ],
    request: ScrapeSourceRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """
    Ejecuta el scraping solo para la fuente indicada.
    Retorna un job_id para consultar el estado.
    """
    sources = get_news_sources()
    if not any(s["id"].lower() == source_id.lower() for s in sources):
        raise HTTPException(status_code=404, detail=f"Fuente '{source_id}' no encontrada.")

    _parse_date_filter(request.fecha_desde)
    _parse_date_filter(request.fecha_hasta)

    params = {"source_id": source_id, **request.model_dump()}
    job = job_store.create(kind="single_source", params=params)

    background_tasks.add_task(
        _run_job,
        job,
        fecha_desde=request.fecha_desde,
        fecha_hasta=request.fecha_hasta,
        fuentes=[source_id],
        force_reprocess=request.force_reprocess,
        html_only=request.html_only,
        include_social=False,
        social_only=False,
    )

    return {"job_id": job.id, "status": job.status, "message": f"Scraping de '{source_id}' iniciado."}


@app.post("/scrape/social", tags=["scraping"], summary="Scrape de redes sociales")
def scrape_social(request: ScrapeSocialRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """
    Ejecuta solo los conectores de redes sociales en background.
    Retorna un job_id para consultar el estado.
    """
    _parse_date_filter(request.fecha_desde)
    _parse_date_filter(request.fecha_hasta)

    params = request.model_dump()
    job = job_store.create(kind="social_only", params=params)

    background_tasks.add_task(
        _run_job,
        job,
        fecha_desde=request.fecha_desde,
        fecha_hasta=request.fecha_hasta,
        fuentes=request.social_ids,
        force_reprocess=request.force_reprocess,
        html_only=False,
        include_social=False,
        social_only=True,
    )

    return {"job_id": job.id, "status": job.status, "message": "Scraping social iniciado en background."}


# ---------------------------------------------------------------------------
# Endpoints — Jobs
# ---------------------------------------------------------------------------

@app.get("/jobs", tags=["jobs"], summary="Listar todos los jobs")
def list_jobs(
    status: Annotated[
        str | None,
        Query(
            description=(
                "Filtrar por estado del job. Valores posibles: "
                "`pending` (en cola), `running` (en ejecución), `done` (completado), `failed` (falló). "
                "Si se omite, retorna todos los jobs."
            ),
            example="done",
        ),
    ] = None,
) -> list[dict[str, Any]]:
    """Retorna todos los jobs registrados, ordenados del más reciente al más antiguo."""
    jobs = job_store.all()
    if status:
        jobs = [j for j in jobs if j.status == status]
    return [j.to_dict() for j in jobs]


@app.get("/jobs/{job_id}", tags=["jobs"], summary="Estado de un job")
def get_job(
    job_id: Annotated[
        str,
        Path(
            description=(
                "ID único del job, retornado por los endpoints de scraping (`POST /scrape/run`, "
                "`POST /scrape/source/{id}`, `POST /scrape/social`). "
                "Formato UUID. Ejemplo: `3fa85f64-5717-4562-b3fc-2c963f66afa6`"
            ),
            example="3fa85f64-5717-4562-b3fc-2c963f66afa6",
        ),
    ],
) -> dict[str, Any]:
    """Retorna el estado actual y estadísticas de un job específico."""
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' no encontrado.")
    return job.to_dict()


# ---------------------------------------------------------------------------
# Endpoints — Artículos
# ---------------------------------------------------------------------------

@app.get("/articles", tags=["artículos"], summary="Listar artículos guardados")
def list_articles(
    source: Annotated[
        str | None,
        Query(
            description=(
                "Filtrar por ID de fuente de noticias. "
                "Si se omite, agrega artículos de todas las fuentes. "
                "Obtén los IDs con `GET /sources` (campo `id`). Ejemplo: `el_pais_cali`"
            ),
            example="el_pais_cali",
        ),
    ] = None,
    fecha_desde: Annotated[
        str | None,
        Query(
            description="Filtrar artículos publicados desde esta fecha, formato **DD/MM/YYYY**.",
            example="01/03/2026",
        ),
    ] = None,
    fecha_hasta: Annotated[
        str | None,
        Query(
            description="Filtrar artículos publicados hasta esta fecha, formato **DD/MM/YYYY**.",
            example="27/03/2026",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Cantidad máxima de artículos a retornar. Rango: 1–500. Por defecto 50.",
            example=50,
        ),
    ] = 50,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Número de artículos a saltar (paginación). Para la segunda página con limit=50, usa offset=50.",
            example=0,
        ),
    ] = 0,
) -> dict[str, Any]:
    """
    Lista artículos almacenados en disco.
    Si no se especifica `source`, agrega todas las fuentes disponibles.
    """
    start = _parse_date_filter(fecha_desde)
    end = _parse_date_filter(fecha_hasta)

    if source:
        sources_to_read = [source]
    else:
        news_sources = get_news_sources()
        sources_to_read = [s["id"] for s in news_sources]

    all_articles: list[dict[str, Any]] = []
    for sid in sources_to_read:
        articles = _load_articles_for_source(sid)
        for a in articles:
            if start or end:
                pub = a.get("fecha_publicacion", "")
                try:
                    pub_dt = datetime.strptime(pub, "%d/%m/%Y")
                except Exception:
                    pub_dt = None
                if pub_dt:
                    if start and pub_dt < start:
                        continue
                    if end and pub_dt > end:
                        continue
            all_articles.append(a)

    total = len(all_articles)
    page = all_articles[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "count": len(page),
        "articles": page,
    }


@app.get("/articles/{article_id}", tags=["artículos"], summary="Obtener artículo por ID")
def get_article(
    article_id: Annotated[
        int,
        Path(
            description=(
                "Número entero `id_noticia` del artículo. "
                "Obtén este valor desde el campo `id_noticia` en la respuesta de `GET /articles`."
            ),
            example=1,
        ),
    ],
    source: Annotated[
        str,
        Query(
            description=(
                "ID de la fuente a la que pertenece el artículo (requerido). "
                "Obtén los IDs con `GET /sources` (campo `id`). Ejemplo: `el_pais_cali`"
            ),
            example="el_pais_cali",
        ),
    ],
) -> dict[str, Any]:
    """Retorna un artículo específico por su id_noticia y fuente."""
    articles = _load_articles_for_source(source)
    match = next((a for a in articles if a.get("id_noticia") == article_id), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Artículo {article_id} no encontrado en fuente '{source}'.")
    return match


# ---------------------------------------------------------------------------
# Endpoints — Estadísticas de almacenamiento
# ---------------------------------------------------------------------------

@app.get("/stats", tags=["sistema"], summary="Estadísticas de almacenamiento")
def storage_stats() -> dict[str, Any]:
    """Retorna conteos de artículos almacenados por fuente."""
    cfg = _load_app_cfg()
    parsed_dir = Path(cfg["paths"]["parsed_json_dir"])
    news_sources = get_news_sources()

    result: dict[str, Any] = {"sources": {}, "total_articles": 0}

    for s in news_sources:
        sid = s["id"]
        json_path = parsed_dir / f"{sid}.json"
        if json_path.exists():
            try:
                articles = json.loads(json_path.read_text(encoding="utf-8"))
                count = len(articles)
            except Exception:
                count = 0
        else:
            count = 0
        result["sources"][sid] = count
        result["total_articles"] += count

    jobs_summary = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for job in job_store.all():
        jobs_summary[job.status] = jobs_summary.get(job.status, 0) + 1
    result["jobs"] = jobs_summary

    return result
