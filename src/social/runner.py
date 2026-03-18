from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.extractors.validators import validate_article_payload
from src.nlp.minimal_processor import enrich_payload
from src.scrapers.cloudflare_scraper import CloudflareScraper
from src.scrapers.requests_fallback import RequestsScraper
from src.scrapers.selenium_scraper import SeleniumScraper
from src.social.facebook_connector import FacebookConnector
from src.social.instagram_connector import InstagramConnector
from src.social.nitter_connector import NitterConnector
from src.social.youtube_connector import YouTubeConnector
from src.utils.output_payload import normalize_output_payload


def _load_social_sources(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = loaded.get("sources", []) if isinstance(loaded, dict) else []
    return [item for item in items if isinstance(item, dict) and bool(item.get("enabled", True))]


def _fetch_any(url: str, fetchers: list[tuple[str, Any]]) -> str:
    errors: list[str] = []
    for name, scraper in fetchers:
        try:
            return scraper.fetch_html(url)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("; ".join(errors) if errors else "sin fetchers sociales disponibles")


def _connector_for(source: dict, fetch_html, browser_fetch_html):
    connector_type = str(source.get("type", "")).lower()
    if connector_type == "nitter":
        return NitterConnector(source, fetch_html=fetch_html, browser_fetch_html=browser_fetch_html)
    if connector_type == "youtube":
        return YouTubeConnector(source, fetch_html=fetch_html, browser_fetch_html=browser_fetch_html)
    if connector_type == "facebook":
        return FacebookConnector(source, fetch_html=fetch_html, browser_fetch_html=browser_fetch_html)
    if connector_type == "instagram":
        return InstagramConnector(source, fetch_html=fetch_html, browser_fetch_html=browser_fetch_html)
    raise ValueError(f"Tipo de conector social no soportado: {connector_type}")


def run_social_sources(
    *,
    root: Path,
    app_cfg: dict[str, Any],
    store,
    log: logging.Logger,
    start_date: datetime | None,
    end_date: datetime | None,
    force_reprocess: bool,
    allowed_ids: set[str] | None = None,
) -> dict[str, int]:
    social_sources = _load_social_sources(root / "config" / "social_sources.yaml")
    if allowed_ids is not None:
        social_sources = [item for item in social_sources if str(item.get("id", "")).lower() in allowed_ids]

    timeout_seconds = int(app_cfg.get("request_timeout_seconds", 25))
    fetchers: list[tuple[str, Any]] = [("requests", RequestsScraper(timeout_seconds=timeout_seconds))]
    if bool(app_cfg.get("use_cloudflare_scraper", True)):
        try:
            fetchers.append(("cloudflare", CloudflareScraper(timeout_seconds=timeout_seconds)))
        except Exception as exc:
            log.warning("Cloudflare social scraper deshabilitado: %s", exc)

    browser_fetch_html = None
    browser_scraper = None
    requires_browser = any(
        str(source.get("type", "")).lower() in {"youtube", "facebook", "instagram"}
        or bool(source.get("prefer_browser", False))
        for source in social_sources
    )
    if bool(app_cfg.get("use_selenium_scraper", False)) or requires_browser:
        try:
            browser_scraper = SeleniumScraper(
                timeout_seconds=int(app_cfg.get("selenium_timeout_seconds", 30)),
                headless=bool(app_cfg.get("selenium_headless", True)),
            )
            browser_fetch_html = browser_scraper.fetch_html
        except Exception as exc:
            log.warning("Browser social scraper deshabilitado: %s", exc)

    stats = {"social_sources": 0, "social_seen": 0, "social_saved": 0, "social_failed": 0}

    try:
        for source in social_sources:
            sid = str(source["id"])
            source_json_path = store.parsed_dir / f"{sid}.json"
            existing_items: list[dict[str, Any]] = []
            existing_urls: set[str] = set()
            if not force_reprocess and source_json_path.exists():
                try:
                    existing_items = json.loads(source_json_path.read_text(encoding="utf-8"))
                    existing_urls = {str(item.get("url_noticia", "")) for item in existing_items}
                except Exception:
                    existing_items = []
                    existing_urls = set()

            connector = _connector_for(source, lambda url: _fetch_any(url, fetchers), browser_fetch_html)
            stats["social_sources"] += 1
            log.info("=== Fuente social: %s ===", sid)

            try:
                items = connector.fetch_items(
                    start_date=start_date,
                    end_date=end_date,
                    keywords=list(app_cfg.get("keywords", [])),
                )
            except Exception as exc:
                stats["social_failed"] += 1
                log.warning("Error procesando fuente social %s: %s", sid, exc)
                continue

            new_items: list[dict[str, Any]] = []
            for item in items:
                stats["social_seen"] += 1
                url = str(item.get("url_noticia", ""))
                if not force_reprocess and url in existing_urls:
                    continue
                try:
                    enriched = enrich_payload(item, app_cfg)
                    validated = validate_article_payload(enriched)
                    payload = normalize_output_payload(
                        enriched | {"url_noticia": str(validated.url_noticia)},
                        default_source_type="social",
                    )
                    new_items.append(payload)
                    stats["social_saved"] += 1
                except Exception as exc:
                    stats["social_failed"] += 1
                    log.warning("Item social invalido en %s: %s", sid, exc)

            if existing_items or new_items:
                all_items = existing_items + new_items
                deduped: list[dict[str, Any]] = []
                seen_urls: set[str] = set()
                for payload in all_items:
                    url = str(payload.get("url_noticia", ""))
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    deduped.append(normalize_output_payload(payload, default_source_type="social"))

                source_json_path.parent.mkdir(parents=True, exist_ok=True)
                source_json_path.write_text(json.dumps(deduped, indent=2, ensure_ascii=False), encoding="utf-8")
                log.info("Fuente social %s: +%d nuevas / %d total -> %s", sid, len(new_items), len(deduped), source_json_path)
    finally:
        for _, scraper in fetchers:
            if hasattr(scraper, "session") and getattr(scraper, "session") is not None:
                try:
                    scraper.session.close()
                except Exception:
                    pass
        if browser_scraper is not None:
            try:
                browser_scraper.close()
            except Exception:
                pass

    return stats
