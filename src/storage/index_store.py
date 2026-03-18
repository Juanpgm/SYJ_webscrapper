import json
import threading
from pathlib import Path
from typing import Any


class IndexStore:
    def __init__(self, checkpoints_dir: str) -> None:
        self.path = Path(checkpoints_dir) / "article_index.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"items": {}}, indent=2), encoding="utf-8")
        self._lock = threading.Lock()
        self._dirty = False
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        with self._lock:
            self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            self._dirty = False

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._data.get("items", {}).get(key)

    def upsert(self, key: str, payload: dict[str, Any], persist: bool = True) -> None:
        with self._lock:
            self._data.setdefault("items", {})[key] = payload
            self._dirty = True
        if persist:
            self.save()

    def flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
        self.save()
