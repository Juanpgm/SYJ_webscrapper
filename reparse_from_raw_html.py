from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from src.extractors.article_parser import extract_article_payload
from src.extractors.validators import validate_article_payload
from src.utils.output_payload import normalize_output_payload


def load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def load_sources(source_dir: Path) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for fp in sorted(source_dir.glob("*.yaml")):
        if fp.name == "catalog.yaml":
            continue
        src = load_yaml(fp)
        sid = src.get("id")
        if isinstance(sid, str) and sid:
            by_id[sid] = src
    return by_id


def main() -> None:
    root = Path.cwd()
    cfg = load_yaml(root / "config" / "scraper_config.yaml")
    paths = cfg.get("paths", {})

    raw_root = root / str(paths.get("raw_html_dir", "data/raw_html"))
    parsed_root = root / str(paths.get("parsed_json_dir", "data/parsed_json"))
    checkpoints_root = root / str(paths.get("checkpoints_dir", "data/checkpoints"))

    index_path = checkpoints_root / "article_index.json"
    profiles_path = checkpoints_root / "source_profiles.json"

    index_items = {}
    if index_path.exists():
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        index_items = index_data.get("items", {}) if isinstance(index_data, dict) else {}

    source_profiles = {}
    if profiles_path.exists():
        profiles_data = json.loads(profiles_path.read_text(encoding="utf-8"))
        source_profiles = profiles_data.get("sources", {}) if isinstance(profiles_data, dict) else {}

    sources = load_sources(root / "config" / "sources")

    processed = 0
    saved = 0
    failed = 0
    missing_index = 0

    for source_dir in sorted([p for p in raw_root.iterdir() if p.is_dir()]):
        source_id = source_dir.name
        source_cfg = sources.get(source_id, {})
        source_name = source_cfg.get("name", source_id)
        selectors = source_profiles.get(source_id) or source_cfg.get("selectors") or {}
        if not isinstance(selectors, dict):
            selectors = {}

        for day_dir in sorted([p for p in source_dir.iterdir() if p.is_dir()]):
            out_day_dir = parsed_root / source_id / day_dir.name
            out_day_dir.mkdir(parents=True, exist_ok=True)

            for html_fp in sorted(day_dir.glob("*.html")):
                processed += 1
                aid = html_fp.stem
                index_item = index_items.get(aid)
                article_url = ""
                fetcher = "raw_html"
                if isinstance(index_item, dict):
                    article_url = str(index_item.get("url") or "")
                    fetcher = str(index_item.get("fetcher") or fetcher)
                if not article_url:
                    missing_index += 1
                    # Keep traceable URL-like value even if index was missing.
                    article_url = f"https://unknown.local/{source_id}/{aid}"

                json_fp = out_day_dir / f"{aid}.json"

                try:
                    html = html_fp.read_text(encoding="utf-8", errors="ignore")
                    payload = extract_article_payload(html, source_name, article_url, selectors)
                    validated = validate_article_payload(payload)
                    output = normalize_output_payload(
                        payload
                        | {
                            "url_noticia": str(validated.url_noticia),
                            "fetcher": fetcher,
                            "source_id": source_id,
                        },
                        default_source_type="news",
                    )
                    json_fp.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
                    saved += 1
                except Exception as exc:
                    failed += 1
                    fail_dir = root / str(paths.get("failed_dir", "data/failed")) / source_id
                    fail_dir.mkdir(parents=True, exist_ok=True)
                    (fail_dir / f"{aid}.json").write_text(
                        json.dumps(
                            {
                                "url_noticia": article_url,
                                "fuente": source_id,
                                "fetcher": fetcher,
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

    print(
        json.dumps(
            {
                "processed_html": processed,
                "json_saved": saved,
                "failed": failed,
                "missing_index_url": missing_index,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
