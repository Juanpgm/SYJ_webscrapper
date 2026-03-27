"""
Worker de una sola emisora.

Loop infinito con manejo de caídas:
  1. Watcher → detectar si hay stream activo (polling)
  2. Extrae URL de audio HLS con yt-dlp
  3. Captura audio via ffmpeg → chunks numpy
  4. Transcribe con Whisper (VAD descarta música)
  5. Si el stream cae → regresa al paso 1 sin detenerse

El stop_event permite parar limpiamente desde el manager.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from src.radio import transcriber as transcriber_mod
from src.radio.capture import audio_chunks
from src.radio.models import StationState, TranscriptionEntry
from src.radio.watcher import get_audio_stream_url

if TYPE_CHECKING:
    from src.radio.models import RadioStation
    from src.radio.storage import RadioStorage


def run_station(
    station: "RadioStation",
    state: StationState,
    storage: "RadioStorage",
    stop_event: threading.Event,
    settings: dict[str, Any],
    broadcast_cb: Any = None,          # callable(entry) para SSE
) -> None:
    """
    Función principal del worker. Diseñada para correr en un hilo dedicado.

    Args:
        station: Configuración de la emisora.
        state: Objeto mutable compartido con la API (status, stats, etc.).
        storage: Instancia de RadioStorage para persistencia.
        stop_event: threading.Event — setear para detener limpiamente.
        settings: Dict de config (chunk_duration, poll_interval, etc.).
        broadcast_cb: Función llamada con cada TranscriptionEntry (para SSE).
    """
    log = logging.getLogger(f"radio.worker.{station.id}")

    poll_interval: int = int(settings.get("poll_interval_seconds", 120))
    chunk_duration: int = int(settings.get("chunk_duration_seconds", 30))
    language: str = settings.get("language", "es")
    vad_filter: bool = bool(settings.get("vad_filter", True))
    vad_min_silence: int = int(settings.get("vad_min_silence_ms", 500))

    state.started_at = datetime.now(timezone.utc).isoformat()

    while not stop_event.is_set():

        # ── Fase 1: Watcher ─────────────────────────────────────────────
        state.status = "watching"
        log.info("[%s] Buscando stream activo en %s ...", station.name, station.channel_url)

        audio_url: str | None = None
        while not stop_event.is_set():
            try:
                audio_url = get_audio_stream_url(station.channel_url)
            except Exception as exc:
                log.debug("[%s] get_audio_stream_url error: %s", station.name, exc)
                audio_url = None

            if audio_url:
                state.live_url = station.channel_url
                state.last_seen_live = datetime.now(timezone.utc).isoformat()
                log.info("[%s] Stream detectado. Iniciando captura.", station.name)
                break

            log.debug("[%s] Offline. Reintentando en %ds.", station.name, poll_interval)
            stop_event.wait(poll_interval)

        if stop_event.is_set():
            break

        # ── Fase 2: Captura + Transcripción ─────────────────────────────
        state.status = "transcribing"
        log.info("[%s] Capturando audio (chunk=%ds) ...", station.name, chunk_duration)

        try:
            for chunk_audio in audio_chunks(audio_url, chunk_duration=chunk_duration):  # type: ignore[arg-type]
                if stop_event.is_set():
                    break

                try:
                    segments = transcriber_mod.transcribe(
                        chunk_audio,
                        language=language,
                        vad_filter=vad_filter,
                        vad_min_silence_ms=vad_min_silence,
                    )
                except Exception as exc:
                    log.warning("[%s] Error transcribiendo chunk: %s", station.name, exc)
                    continue

                if not segments:
                    log.debug("[%s] Chunk sin voz detectada (música/silencio).", station.name)
                    continue

                ts = datetime.now(timezone.utc).isoformat()
                for seg in segments:
                    entry = TranscriptionEntry(
                        station_id=station.id,
                        station_name=station.name,
                        timestamp=ts,
                        chunk_start=seg["start"],
                        chunk_end=seg["end"],
                        text=seg["text"],
                        confidence=seg["confidence"],
                    )
                    storage.append(entry)
                    state.segments_total += 1

                    if broadcast_cb:
                        try:
                            broadcast_cb(entry)
                        except Exception:
                            pass

                    log.info("[%s] %.1f-%.1fs | %s", station.name, seg["start"], seg["end"], seg["text"][:80])

        except Exception as exc:
            state.last_error = str(exc)
            log.warning("[%s] Stream cortado: %s. Reconectando...", station.name, exc)

        if stop_event.is_set():
            break

        # ── Fase 3: Stream caído → back to watcher ──────────────────────
        state.status = "reconnecting"
        state.live_url = None
        log.info("[%s] Reiniciando ciclo en 10s...", station.name)
        stop_event.wait(10)

    state.status = "stopped"
    state.live_url = None
    log.info("[%s] Worker detenido limpiamente.", station.name)
