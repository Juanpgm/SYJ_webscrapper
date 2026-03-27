"""
Adapter que expone la lógica del orquestador como función Python callable
(sin argparse), para ser invocada desde la API.
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.discovery.google_discovery import discover_articles_with_google
from src.extractors.article_parser import discover_article_urls, extract_article_payload
from src.extractors.source_profiler import infer_best_selectors
from src.extractors.validators import validate_article_payload
from src.nlp.minimal_processor import enrich_payload
from src.scrapers.cloudflare_scraper import CloudflareScraper
from src.scrapers.requests_fallback import RequestsScraper
from src.scrapers.selenium_scraper import SeleniumScraper
from src.social.runner import run_social_sources
from src.storage.fs_store import FileStore
from src.storage.index_store import IndexStore
from src.storage.profile_store import ProfileStore
from src.utils.hashing import url_hash
from src.utils.output_payload import normalize_output_payload

ROOT = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_sources(source_dir: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for fp in sorted(source_dir.glob("*.yaml")):
        if fp.name == "catalog.yaml":
            continue
        loaded = _load_yaml(fp)
        if isinstance(loaded, dict):
            items.append(loaded)
    return items


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%d/%m/%Y")


def _in_range(date_str: str, start: datetime | None, end: datetime | None) -> bool:
    try:
        value = datetime.strptime(date_str, "%d/%m/%Y")
    except Exception:
        return True
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def _pick_http_scrapers(config: dict[str, Any], log: logging.Logger) -> list[tuple[str, Any]]:
    timeout_seconds = int(config.get("request_timeout_seconds", 25))
    scrapers: list[tuple[str, Any]] = [("requests", RequestsScraper(timeout_seconds=timeout_seconds))]

    if bool(config.get("use_cloudflare_scraper", True)):
        try:
            scrapers.append(("cloudflare", CloudflareScraper(timeout_seconds=timeout_seconds)))
        except Exception as exc:
            log.warning("Cloudflare scraper deshabilitado: %s", exc)

    if bool(config.get("use_selenium_scraper", False)):
        try:
            selenium_timeout = int(config.get("selenium_timeout_seconds", timeout_seconds))
            selenium_headless = bool(config.get("selenium_headless", True))
            scrapers.append(("selenium", SeleniumScraper(timeout_seconds=selenium_timeout, headless=selenium_headless)))
        except Exception as exc:
            log.warning("Selenium scraper deshabilitado: %s", exc)

    return scrapers


def _fetch_http_first(
    url: str,
    http_scrapers: list[tuple[str, Any]],
    *,
    parallel_fetch: bool,
    parallel_timeout_seconds: float,
) -> tuple[str, str]:
    if not http_scrapers:
        raise RuntimeError("No hay scrapers HTTP disponibles")

    if parallel_fetch and len(http_scrapers) > 1 and not any(name == "selenium" for name, _ in http_scrapers):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=len(http_scrapers)) as pool:
            futures = {pool.submit(scraper.fetch_html, url): name for name, scraper in http_scrapers}
            errors: list[str] = []
            for future in as_completed(futures, timeout=parallel_timeout_seconds):
                name = futures[future]
                try:
                    html = future.result()
                    return html, name
                except Exception as exc:
                    elapsed = time.perf_counter() - started
                    errors.append(f"{name} ({elapsed:.2f}s): {exc}")
            raise RuntimeError("; ".join(errors) if errors else "sin respuesta HTTP")

    errors2: list[str] = []
    for name, scraper in http_scrapers:
        try:
            return scraper.fetch_html(url), name
        except Exception as exc:
            errors2.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors2))


def get_news_sources() -> list[dict[str, Any]]:
    """Retorna la lista de fuentes de noticias configuradas."""
    return _load_sources(ROOT / "config" / "sources")


def get_social_sources() -> list[dict[str, Any]]:
    """Retorna la lista de fuentes sociales configuradas."""
    social_cfg_path = ROOT / "config" / "social_sources.yaml"
    if not social_cfg_path.exists():
        return []
    data = _load_yaml(social_cfg_path)
    sources = data.get("sources", [])
    return sources if isinstance(sources, list) else []


def run_pipeline(
    *,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    fuentes: list[str] | None = None,
    force_reprocess: bool = False,
    html_only: bool = False,
    include_social: bool = False,
    social_only: bool = False,
    log: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    Ejecuta el pipeline de scraping con parámetros Python (sin argparse).
    Retorna un dict con estadísticas de la ejecución.
    """
    if log is None:
        log = logging.getLogger("scraper.api")

    app_cfg = _load_yaml(ROOT / "config" / "scraper_config.yaml")
    sources = _load_sources(ROOT / "config" / "sources")

    allow: set[str] | None = None
    if fuentes:
        allow = {s.lower() for s in fuentes}
        sources = [s for s in sources if s["id"].lower() in allow]

    if social_only:
        sources = []

    paths = app_cfg["paths"]
    store = FileStore(paths["raw_html_dir"], paths["parsed_json_dir"], paths["failed_dir"])
    index = IndexStore(paths["checkpoints_dir"])
    profiles = ProfileStore(paths["checkpoints_dir"])

    start = _parse_date(fecha_desde)
    end = _parse_date(fecha_hasta)

    parallel_fetch = bool(app_cfg.get("parallel_fetch", True))
    parallel_timeout_seconds = float(app_cfg.get("parallel_fetch_timeout_seconds", 30))
    max_parallel_articles = max(1, int(app_cfg.get("max_parallel_articles", 24)))

    http_scrapers = _pick_http_scrapers(app_cfg, log)

    stats: dict[str, Any] = {
        "sources": 0,
        "urls_seen": 0,
        "html_saved": 0,
        "json_saved": 0,
        "skipped": 0,
        "failed": 0,
    }

    def _fetch_any(url: str) -> tuple[str, str]:
        return _fetch_http_first(
            url,
            http_scrapers,
            parallel_fetch=parallel_fetch,
            parallel_timeout_seconds=parallel_timeout_seconds,
        )

    try:
        for source in sources:
            sid = source["id"]
            stats["sources"] += 1
            log.info("=== Fuente: %s ===", sid)

            configured_max = int(app_cfg.get("max_articles_per_source", 200))
            source_max = configured_max if configured_max > 0 else 10**9

            discovered: list[str] = discover_articles_with_google(
                source=source,
                fetch_html=lambda url: _fetch_any(url)[0],
                start_date=start,
                end_date=end,
                max_results=source_max,
                security_keywords=app_cfg.get("keywords", []),
                max_queries_per_source=int(app_cfg.get("google_max_queries_per_source", 220)),
                max_queries_per_run=int(app_cfg.get("google_max_queries_per_run", 30)),
                parallel_queries=int(app_cfg.get("google_parallel_queries", 8)),
                enforce_security_focus=bool(app_cfg.get("google_security_focus", True)),
                pages_per_query=int(app_cfg.get("google_pages_per_query", 1)),
                results_per_page=int(app_cfg.get("google_results_per_page", 20)),
            )

            if not discovered:
                for listing_url in source.get("listing_urls", []):
                    try:
                        html, fetcher = _fetch_any(listing_url)
                        links = discover_article_urls(html, source["base_url"], source.get("link_selectors", []))
                        discovered.extend(links)
                        log.info("Listing con %s -> %d links", fetcher, len(links))
                    except Exception as exc:
                        log.warning("Error listing_url=%s: %s", listing_url, exc)

            discovered = list(dict.fromkeys(discovered))[:source_max]
            log.info("URLs descubiertas para %s: %d", sid, len(discovered))

            profile = profiles.get(sid)
            source_selectors: dict[str, Any] = source.get("selectors") or {}
            if profile:
                source_selectors = profile
            elif discovered:
                sample_html: list[str] = []
                for url in discovered[:3]:
                    try:
                        html, _ = _fetch_any(url)
                        sample_html.append(html)
                    except Exception:
                        continue
                if sample_html:
                    profiled = infer_best_selectors(source, sample_html)
                    profiles.upsert(sid, profiled)
                    source_selectors = profiled

            if not isinstance(source_selectors, dict):
                source_selectors = {}

            day_folder = datetime.now().strftime("%Y-%m-%d")
            source_json_path = store.parsed_dir / f"{sid}.json"

            existing_articles: list[dict[str, Any]] = []
            existing_urls: set[str] = set()
            if not force_reprocess and source_json_path.exists():
                try:
                    existing_articles = json.loads(source_json_path.read_text(encoding="utf-8"))
                    existing_urls = {str(a.get("url_noticia", "")) for a in existing_articles}
                except Exception:
                    existing_articles = []
                    existing_urls = set()

            new_articles: list[dict[str, Any]] = []

            def _process_article(article_url: str) -> dict[str, Any]:
                result = {"urls_seen": 1, "html_saved": 0, "json_saved": 0, "skipped": 0, "failed": 0}
                aid = url_hash(article_url)
                html_path = store.raw_html_path(sid, day_folder, aid)

                if not force_reprocess and article_url in existing_urls:
                    result["skipped"] = 1
                    return result

                try:
                    if html_path.exists():
                        article_html = html_path.read_text(encoding="utf-8")
                        fetcher = "cache"
                    else:
                        article_html, fetcher = _fetch_any(article_url)
                        store.save_html(html_path, article_html)
                        result["html_saved"] = 1

                    index.upsert(
                        aid,
                        {"source": sid, "url": article_url, "html_path": str(html_path), "fetcher": fetcher},
                        persist=False,
                    )

                    if html_only:
                        return result

                    payload = extract_article_payload(article_html, source["name"], article_url, source_selectors)
                    if not _in_range(payload["fecha_publicacion"], start, end):
                        result["skipped"] = 1
                        return result

                    enriched = enrich_payload(payload, app_cfg)
                    validated = validate_article_payload(enriched)
                    article_data = normalize_output_payload(
                        enriched | {"url_noticia": str(validated.url_noticia), "fetcher": fetcher},
                        default_source_type="news",
                    )
                    new_articles.append(article_data)
                    result["json_saved"] = 1
                    return result
                except Exception as exc:
                    result["failed"] = 1
                    fail_path = store.failed_path(sid, aid)
                    fail_path.write_text(
                        json.dumps({"url_noticia": article_url, "fuente": sid, "error": str(exc)}, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    return result

            workers = min(max_parallel_articles, max(1, len(discovered)))
            if workers == 1:
                for url in discovered:
                    outcome = _process_article(url)
                    for k in ("urls_seen", "html_saved", "json_saved", "skipped", "failed"):
                        stats[k] += int(outcome.get(k, 0))
            else:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = [pool.submit(_process_article, url) for url in discovered]
                    for fut in as_completed(futs):
                        outcome = fut.result()
                        for k in ("urls_seen", "html_saved", "json_saved", "skipped", "failed"):
                            stats[k] += int(outcome.get(k, 0))

            index.flush()

            if not html_only and (existing_articles or new_articles):
                all_articles = existing_articles + new_articles
                deduped: list[dict[str, Any]] = []
                seen_urls: set[str] = set()
                for item in all_articles:
                    url = str(item.get("url_noticia", ""))
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    deduped.append(normalize_output_payload(item, default_source_type="news"))

                for idx, article in enumerate(deduped, start=1):
                    article["id_noticia"] = idx

                source_json_path.parent.mkdir(parents=True, exist_ok=True)
                source_json_path.write_text(
                    json.dumps(deduped, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                log.info("Fuente %s: +%d nuevas / %d total", sid, len(new_articles), len(deduped))

        if include_social or social_only or bool(app_cfg.get("include_social_sources", False)):
            social_stats = run_social_sources(
                root=ROOT,
                app_cfg=app_cfg,
                store=store,
                log=log,
                start_date=start,
                end_date=end,
                force_reprocess=force_reprocess,
                allowed_ids=allow,
            )
            stats.update(social_stats)

    finally:
        for _, scraper in http_scrapers:
            for attr in ("close", "session"):
                obj = getattr(scraper, attr, None)
                if obj is None:
                    continue
                try:
                    (obj() if callable(obj) else obj.close())
                except Exception:
                    pass

    log.info("=== Resumen pipeline: %s ===", stats)
    return stats
