import json
from pathlib import Path
from typing import Any


class ProfileStore:
    def __init__(self, checkpoints_dir: str) -> None:
        self.path = Path(checkpoints_dir) / "source_profiles.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"sources": {}}, indent=2), encoding="utf-8")
        self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, source_id: str) -> dict[str, Any] | None:
        return self._data.get("sources", {}).get(source_id)

    def upsert(self, source_id: str, selectors: dict[str, Any]) -> None:
        self._data.setdefault("sources", {})[source_id] = selectors
        self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
