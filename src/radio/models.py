from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RadioStation:
    id: str
    name: str
    channel_url: str
    enabled: bool = True


@dataclass
class TranscriptionEntry:
    station_id: str
    station_name: str
    timestamp: str          # ISO 8601
    chunk_start: float      # segundos dentro del chunk ffmpeg
    chunk_end: float
    text: str
    confidence: float       # avg_logprob de Whisper

    def to_dict(self) -> dict[str, Any]:
        return {
            "station_id": self.station_id,
            "station_name": self.station_name,
            "timestamp": self.timestamp,
            "chunk_start": round(self.chunk_start, 2),
            "chunk_end": round(self.chunk_end, 2),
            "text": self.text,
            "confidence": self.confidence,
        }


@dataclass
class StationState:
    station: RadioStation
    status: str = "stopped"       # stopped | watching | connecting | transcribing | reconnecting | error
    live_url: str | None = None   # URL de YouTube del stream activo
    last_seen_live: str | None = None
    segments_total: int = 0
    last_error: str | None = None
    started_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.station.id,
            "name": self.station.name,
            "channel_url": self.station.channel_url,
            "enabled": self.station.enabled,
            "status": self.status,
            "live_url": self.live_url,
            "last_seen_live": self.last_seen_live,
            "segments_total": self.segments_total,
            "last_error": self.last_error,
            "started_at": self.started_at,
        }
