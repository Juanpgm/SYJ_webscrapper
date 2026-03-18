import json
from pathlib import Path


class FileStore:
    def __init__(self, raw_dir: str, parsed_dir: str, failed_dir: str) -> None:
        self.raw_dir = Path(raw_dir)
        self.parsed_dir = Path(parsed_dir)
        self.failed_dir = Path(failed_dir)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.parsed_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def _source_day_dir(self, root: Path, source: str, yyyy_mm_dd: str) -> Path:
        path = root / source / yyyy_mm_dd
        path.mkdir(parents=True, exist_ok=True)
        return path

    def raw_html_path(self, source: str, yyyy_mm_dd: str, article_id: str) -> Path:
        return self._source_day_dir(self.raw_dir, source, yyyy_mm_dd) / f"{article_id}.html"

    def parsed_json_path(self, source: str, yyyy_mm_dd: str, article_id: str) -> Path:
        return self._source_day_dir(self.parsed_dir, source, yyyy_mm_dd) / f"{article_id}.json"

    def failed_path(self, source: str, article_id: str) -> Path:
        path = self.failed_dir / source
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{article_id}.json"

    def save_html(self, path: Path, html: str) -> None:
        path.write_text(html, encoding="utf-8")

    def save_json(self, path: Path, payload: dict) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
