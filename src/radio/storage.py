"""
Persistencia de transcripciones en formato JSONL.
Un archivo por emisora: data/radio_transcriptions/{station_id}.jsonl

JSONL = una línea JSON por segmento → append eficiente sin reescribir el archivo.
"""
from __future__ import annotations

import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from src.radio.models import TranscriptionEntry


class RadioStorage:
    def __init__(self, output_dir: str | Path, max_memory: int = 200) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_memory = max_memory
        # Buffer en memoria por emisora para consultas rápidas desde la API
        self._buffers: dict[str, deque[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def _jsonl_path(self, station_id: str) -> Path:
        return self._dir / f"{station_id}.jsonl"

    def append(self, entry: TranscriptionEntry) -> None:
        record = entry.to_dict()
        record.setdefault("timestamp", datetime.now().isoformat())

        # Escritura en disco (append)
        jsonl_path = self._jsonl_path(entry.station_id)
        with self._lock:
            with jsonl_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

            # Buffer en memoria
            buf = self._buffers.setdefault(entry.station_id, deque(maxlen=self._max_memory))
            buf.append(record)

    def recent(
        self,
        station_id: str | None = None,
        limit: int = 50,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retorna las transcripciones más recientes.
        Si station_id es None, agrega todas las emisoras.
        since: ISO timestamp — filtra solo entradas posteriores.
        """
        with self._lock:
            if station_id:
                entries = list(self._buffers.get(station_id, []))
            else:
                entries = []
                for buf in self._buffers.values():
                    entries.extend(buf)
                entries.sort(key=lambda x: x.get("timestamp", ""))

        if since:
            entries = [e for e in entries if e.get("timestamp", "") > since]

        return entries[-limit:]

    def load_from_disk(self, station_id: str, last_n: int = 500) -> list[dict[str, Any]]:
        """Carga las últimas N entradas del JSONL (útil al reiniciar la API)."""
        path = self._jsonl_path(station_id)
        if not path.exists():
            return []
        lines: list[str] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    lines.append(line)
        tail = lines[-last_n:]
        result = []
        for line in tail:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result

    def stats(self) -> dict[str, Any]:
        """Retorna conteos de segmentos por emisora."""
        result: dict[str, Any] = {}
        with self._lock:
            for sid, buf in self._buffers.items():
                result[sid] = {
                    "in_memory": len(buf),
                    "on_disk": self._count_lines(self._jsonl_path(sid)),
                }
        return result

    @staticmethod
    def _count_lines(path: Path) -> int:
        if not path.exists():
            return 0
        try:
            with path.open("rb") as fh:
                return sum(1 for _ in fh)
        except Exception:
            return 0
