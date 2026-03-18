from __future__ import annotations

import argparse
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
from src.utils.logging_config import configure_logging
from src.utils.output_payload import normalize_output_payload


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
            selenium_timeout_seconds = int(config.get("selenium_timeout_seconds", timeout_seconds))
            selenium_headless = bool(config.get("selenium_headless", True))
            scrapers.append(
                (
                    "selenium",
                    SeleniumScraper(timeout_seconds=selenium_timeout_seconds, headless=selenium_headless),
                )
            )
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

    errors: list[str] = []
    for name, scraper in http_scrapers:
        try:
            return scraper.fetch_html(url), name
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors))


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Scraper Cali HTTP-only: requests + cloudflare")
    parser.add_argument("--fecha-desde", dest="fecha_desde", type=str, default=None, help="dd/mm/aaaa")
    parser.add_argument("--fecha-hasta", dest="fecha_hasta", type=str, default=None, help="dd/mm/aaaa")
    parser.add_argument("--fuentes", dest="fuentes", nargs="*", default=None)
    parser.add_argument("--force-reprocess", dest="force_reprocess", action="store_true")
    parser.add_argument("--html-only", dest="html_only", action="store_true")
    parser.add_argument("--include-social", dest="include_social", action="store_true")
    parser.add_argument("--social-only", dest="social_only", action="store_true")
    args = parser.parse_args()

    configure_logging()
    log = logging.getLogger("scraper")

    root = Path.cwd()
    app_cfg = _load_yaml(root / "config" / "scraper_config.yaml")
    sources = _load_sources(root / "config" / "sources")
    if args.fuentes:
        allow = {s.lower() for s in args.fuentes}
        sources = [s for s in sources if s["id"].lower() in allow]
    else:
        allow = None

    if bool(args.social_only):
        sources = []

    paths = app_cfg["paths"]
    store = FileStore(paths["raw_html_dir"], paths["parsed_json_dir"], paths["failed_dir"])
    index = IndexStore(paths["checkpoints_dir"])
    profiles = ProfileStore(paths["checkpoints_dir"])

    start = _parse_date(args.fecha_desde)
    end = _parse_date(args.fecha_hasta)
    force_reprocess = bool(args.force_reprocess)
    html_only = bool(args.html_only)

    parallel_fetch = bool(app_cfg.get("parallel_fetch", True))
    parallel_timeout_seconds = float(app_cfg.get("parallel_fetch_timeout_seconds", 30))
    max_parallel_articles = max(1, int(app_cfg.get("max_parallel_articles", 24)))

    http_scrapers = _pick_http_scrapers(app_cfg, log)

    stats = {"sources": 0, "urls_seen": 0, "html_saved": 0, "json_saved": 0, "skipped": 0, "failed": 0}

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

            configured_max_results = int(app_cfg.get("max_articles_per_source", 200))
            source_max_results = configured_max_results if configured_max_results > 0 else 10**9

            discovered: list[str] = discover_articles_with_google(
                source=source,
                fetch_html=lambda url: _fetch_any(url)[0],
                start_date=start,
                end_date=end,
                max_results=source_max_results,
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
                        log.info("Listing cargado con %s (%s) -> %d links", fetcher, listing_url, len(links))
                    except Exception as exc:
                        log.warning("Error cargando listing_url=%s: %s", listing_url, exc)

            discovered = list(dict.fromkeys(discovered))[:source_max_results]
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
                    log.info("Perfil HTML aprendido para %s", sid)

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

                    enriched_payload = enrich_payload(payload, app_cfg)
                    validated = validate_article_payload(enriched_payload)
                    article_data = normalize_output_payload(
                        enriched_payload
                        | {
                            "url_noticia": str(validated.url_noticia),
                            "fetcher": fetcher,
                        },
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
                    futures = [pool.submit(_process_article, url) for url in discovered]
                    for future in as_completed(futures):
                        outcome = future.result()
                        for k in ("urls_seen", "html_saved", "json_saved", "skipped", "failed"):
                            stats[k] += int(outcome.get(k, 0))

            index.flush()

            if not html_only and (existing_articles or new_articles):
                all_articles = existing_articles + new_articles
                # Deduplicate by URL preserving first-seen order
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
                source_json_path.write_text(json.dumps(deduped, indent=2, ensure_ascii=False), encoding="utf-8")
                log.info("Fuente %s: +%d nuevas / %d total -> %s", sid, len(new_articles), len(deduped), source_json_path)

        if bool(args.include_social) or bool(args.social_only) or bool(app_cfg.get("include_social_sources", False)):
            social_stats = run_social_sources(
                root=root,
                app_cfg=app_cfg,
                store=store,
                log=log,
                start_date=start,
                end_date=end,
                force_reprocess=force_reprocess,
                allowed_ids=allow,
            )
            stats.update(social_stats)

        log.info("=== Resumen final: %s ===", stats)
    except KeyboardInterrupt:
        log.warning("Ejecucion interrumpida por usuario. Resumen parcial: %s", stats)
    finally:
        for _, scraper in http_scrapers:
            if hasattr(scraper, "close") and callable(getattr(scraper, "close")):
                try:
                    scraper.close()
                except Exception:
                    pass
            if hasattr(scraper, "session") and getattr(scraper, "session") is not None:
                try:
                    scraper.session.close()
                except Exception:
                    pass
