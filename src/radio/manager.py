"""
Manager singleton que orquesta todos los workers de emisoras.

Responsabilidades:
- Cargar configuración de radio_sources.yaml
- Iniciar/detener workers en hilos daemon
- Exponer estado de cada emisora a la API
- Gestionar el broadcast de transcripciones a clientes SSE
"""
from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any

import yaml

from src.radio import transcriber as transcriber_mod
from src.radio.models import RadioStation, StationState, TranscriptionEntry
from src.radio.storage import RadioStorage
from src.radio.worker import run_station

log = logging.getLogger("radio.manager")

ROOT = Path(__file__).resolve().parent.parent.parent


def _load_config() -> dict[str, Any]:
    cfg_path = ROOT / "config" / "radio_sources.yaml"
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


class _RadioManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, StationState] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._storage: RadioStorage | None = None
        self._settings: dict[str, Any] = {}
        self._stations: dict[str, RadioStation] = {}

        # Cola para SSE broadcast: guarda TranscriptionEntry
        self._sse_queues: list[queue.Queue[TranscriptionEntry | None]] = []
        self._sse_lock = threading.Lock()

        self._initialized = False

    def _ensure_init(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            cfg = _load_config()
            self._settings = cfg.get("settings", {})

            # Configurar modelo Whisper antes de arrancar workers
            transcriber_mod.configure(
                model=self._settings.get("whisper_model", "small"),
                device=self._settings.get("whisper_device", "cpu"),
                compute_type=self._settings.get("whisper_compute_type", "int8"),
            )

            output_dir = ROOT / self._settings.get("output_dir", "data/radio_transcriptions")
            max_mem = int(self._settings.get("max_memory_entries", 200))
            self._storage = RadioStorage(output_dir, max_memory=max_mem)

            for s_cfg in cfg.get("stations", []):
                station = RadioStation(
                    id=s_cfg["id"],
                    name=s_cfg["name"],
                    channel_url=s_cfg["channel_url"],
                    enabled=s_cfg.get("enabled", True),
                )
                self._stations[station.id] = station
                self._states[station.id] = StationState(station=station)

            self._initialized = True
            log.info("RadioManager inicializado con %d emisoras.", len(self._stations))

    # ── Broadcast SSE ────────────────────────────────────────────────────

    def _broadcast(self, entry: TranscriptionEntry) -> None:
        with self._sse_lock:
            for q in self._sse_queues:
                try:
                    q.put_nowait(entry)
                except queue.Full:
                    pass

    def subscribe_sse(self) -> "queue.Queue[TranscriptionEntry | None]":
        q: queue.Queue[TranscriptionEntry | None] = queue.Queue(maxsize=100)
        with self._sse_lock:
            self._sse_queues.append(q)
        return q

    def unsubscribe_sse(self, q: "queue.Queue[TranscriptionEntry | None]") -> None:
        with self._sse_lock:
            try:
                self._sse_queues.remove(q)
            except ValueError:
                pass

    # ── Control de emisoras ──────────────────────────────────────────────

    def start_station(self, station_id: str) -> bool:
        """Inicia el worker de una emisora. Retorna True si arrancó correctamente."""
        self._ensure_init()

        station = self._stations.get(station_id)
        if not station:
            return False

        with self._lock:
            thread = self._threads.get(station_id)
            if thread and thread.is_alive():
                log.warning("[%s] Worker ya está corriendo.", station_id)
                return False

            stop_event = threading.Event()
            self._stop_events[station_id] = stop_event
            state = self._states[station_id]
            state.status = "watching"
            state.last_error = None

            t = threading.Thread(
                target=run_station,
                kwargs={
                    "station": station,
                    "state": state,
                    "storage": self._storage,
                    "stop_event": stop_event,
                    "settings": self._settings,
                    "broadcast_cb": self._broadcast,
                },
                name=f"radio-{station_id}",
                daemon=True,
            )
            t.start()
            self._threads[station_id] = t
            log.info("[%s] Worker iniciado.", station_id)
            return True

    def stop_station(self, station_id: str) -> bool:
        """Detiene el worker de una emisora. Retorna True si existía."""
        self._ensure_init()
        with self._lock:
            stop_event = self._stop_events.get(station_id)
            if not stop_event:
                return False
            stop_event.set()
            log.info("[%s] Señal de stop enviada.", station_id)
            return True

    def start_all(self, only_enabled: bool = True) -> list[str]:
        """Inicia todas las emisoras (o solo las habilitadas). Retorna IDs iniciadas."""
        self._ensure_init()
        started = []
        for sid, station in self._stations.items():
            if only_enabled and not station.enabled:
                continue
            if self.start_station(sid):
                started.append(sid)
        return started

    def stop_all(self) -> list[str]:
        """Detiene todas las emisoras activas."""
        self._ensure_init()
        stopped = []
        for sid in list(self._states.keys()):
            if self.stop_station(sid):
                stopped.append(sid)
        return stopped

    # ── Consultas de estado ──────────────────────────────────────────────

    def get_states(self) -> list[dict[str, Any]]:
        self._ensure_init()
        result = []
        for sid, state in self._states.items():
            d = state.to_dict()
            thread = self._threads.get(sid)
            d["thread_alive"] = bool(thread and thread.is_alive())
            result.append(d)
        return result

    def get_state(self, station_id: str) -> dict[str, Any] | None:
        self._ensure_init()
        state = self._states.get(station_id)
        if not state:
            return None
        d = state.to_dict()
        thread = self._threads.get(station_id)
        d["thread_alive"] = bool(thread and thread.is_alive())
        return d

    def list_stations(self) -> list[dict[str, Any]]:
        self._ensure_init()
        return [
            {
                "id": s.id,
                "name": s.name,
                "channel_url": s.channel_url,
                "enabled": s.enabled,
            }
            for s in self._stations.values()
        ]

    def storage(self) -> RadioStorage:
        self._ensure_init()
        assert self._storage is not None
        return self._storage

    def settings(self) -> dict[str, Any]:
        self._ensure_init()
        return self._settings


# Singleton accesible desde toda la aplicación
manager = _RadioManager()
