"""
Router FastAPI para el pipeline de radio en vivo.

Endpoints:
  GET  /radio/status                  → Estado de todas las emisoras
  GET  /radio/stations                → Configuración de emisoras
  POST /radio/start                   → Iniciar todas las emisoras habilitadas
  POST /radio/stop                    → Detener todas las emisoras
  POST /radio/stations/{id}/start     → Iniciar emisora específica
  POST /radio/stations/{id}/stop      → Detener emisora específica
  GET  /radio/transcriptions          → Transcripciones recientes (paginado)
  GET  /radio/transcriptions/{id}     → Transcripciones de una emisora
  GET  /radio/stream                  → SSE: stream en vivo de todas las emisoras
  GET  /radio/stream/{station_id}     → SSE: stream de una emisora específica
  GET  /radio/stats                   → Estadísticas de almacenamiento
"""
from __future__ import annotations

import asyncio
import json
import queue
from datetime import datetime
from typing import AsyncGenerator

from typing import Annotated
from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import StreamingResponse

from src.radio.manager import manager

router = APIRouter(prefix="/radio", tags=["radio"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _require_station(station_id: str) -> None:
    stations = {s["id"] for s in manager.list_stations()}
    if station_id not in stations:
        raise HTTPException(status_code=404, detail=f"Emisora '{station_id}' no encontrada.")


async def _sse_generator(
    station_id: str | None = None,
    timeout: float = 30.0,
) -> AsyncGenerator[str, None]:
    """
    Async generator para Server-Sent Events.
    Transmite transcripciones en tiempo real conforme llegan de los workers.

    Envía un comentario keep-alive cada 'timeout' segundos para mantener
    la conexión HTTP abierta.
    """
    q = manager.subscribe_sse()
    loop = asyncio.get_event_loop()

    try:
        while True:
            try:
                # Obtener entrada del queue sin bloquear el event loop
                entry = await loop.run_in_executor(None, lambda: q.get(timeout=timeout))

                if entry is None:
                    # Señal de cierre
                    break

                if station_id and entry.station_id != station_id:
                    continue

                data = json.dumps(entry.to_dict(), ensure_ascii=False)
                yield f"data: {data}\n\n"

            except queue.Empty:
                # Keep-alive para evitar timeout del cliente HTTP
                ts = datetime.now().isoformat()
                yield f": keep-alive {ts}\n\n"

    finally:
        manager.unsubscribe_sse(q)


# ── Estado y configuración ────────────────────────────────────────────────────

@router.get("/status", summary="Estado de todas las emisoras")
def radio_status():
    """Retorna el estado actual de cada worker: offline, watching, transcribing, etc."""
    return manager.get_states()


@router.get("/stations", summary="Listar emisoras configuradas")
def radio_stations():
    """Retorna la lista de emisoras configuradas en radio_sources.yaml."""
    return manager.list_stations()


@router.get("/stats", summary="Estadísticas de almacenamiento")
def radio_stats():
    """Retorna conteos de segmentos guardados por emisora (en memoria y en disco)."""
    return manager.storage().stats()


# ── Control de emisoras ───────────────────────────────────────────────────────

@router.post("/start", summary="Iniciar todas las emisoras habilitadas")
def start_all():
    """
    Arranca el pipeline completo para todas las emisoras con enabled=true.
    Cada emisora corre en su propio hilo daemon.
    """
    started = manager.start_all(only_enabled=True)
    return {
        "started": started,
        "count": len(started),
        "message": f"{len(started)} emisora(s) iniciada(s).",
    }


@router.post("/stop", summary="Detener todas las emisoras")
def stop_all():
    """Envía señal de stop a todos los workers activos."""
    stopped = manager.stop_all()
    return {
        "stopped": stopped,
        "count": len(stopped),
        "message": f"{len(stopped)} emisora(s) detenida(s).",
    }


_STATION_ID_PARAM = Path(
    description=(
        "ID de la emisora de radio. "
        "Obtén los IDs disponibles con `GET /radio/stations` (campo `id`). "
        "Ejemplo: `tropicana_cali`"
    ),
    example="tropicana_cali",
)


@router.post("/stations/{station_id}/start", summary="Iniciar emisora específica")
def start_station(station_id: Annotated[str, _STATION_ID_PARAM]):
    """Inicia el worker de monitoreo para la emisora indicada."""
    _require_station(station_id)
    ok = manager.start_station(station_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f"Emisora '{station_id}' ya está activa.")
    return {"station_id": station_id, "message": "Worker iniciado."}


@router.post("/stations/{station_id}/stop", summary="Detener emisora específica")
def stop_station(station_id: Annotated[str, _STATION_ID_PARAM]):
    """Envía señal de stop al worker de la emisora indicada."""
    _require_station(station_id)
    ok = manager.stop_station(station_id)
    if not ok:
        raise HTTPException(status_code=409, detail=f"Emisora '{station_id}' no estaba activa.")
    return {"station_id": station_id, "message": "Señal de stop enviada."}


@router.get("/stations/{station_id}/status", summary="Estado de una emisora")
def station_status(station_id: Annotated[str, _STATION_ID_PARAM]):
    """Retorna el estado detallado de una emisora específica."""
    _require_station(station_id)
    return manager.get_state(station_id)


# ── Transcripciones ───────────────────────────────────────────────────────────

@router.get("/transcriptions", summary="Transcripciones recientes de todas las emisoras")
def all_transcriptions(
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Máximo de entradas a retornar. Rango: 1–500. Por defecto 50.",
            example=50,
        ),
    ] = 50,
    since: Annotated[
        str | None,
        Query(
            description=(
                "Retornar solo entradas posteriores a este timestamp ISO 8601. "
                "Útil para polling incremental. "
                "Formato: `YYYY-MM-DDTHH:MM:SS`. Ejemplo: `2026-03-27T10:00:00`"
            ),
            example="2026-03-27T10:00:00",
        ),
    ] = None,
):
    """
    Retorna las transcripciones más recientes de todas las emisoras
    ordenadas cronológicamente.
    """
    entries = manager.storage().recent(station_id=None, limit=limit, since=since)
    return {"count": len(entries), "transcriptions": entries}


@router.get("/transcriptions/{station_id}", summary="Transcripciones de una emisora")
def station_transcriptions(
    station_id: Annotated[str, _STATION_ID_PARAM],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=500,
            description="Máximo de entradas a retornar. Rango: 1–500. Por defecto 50.",
            example=50,
        ),
    ] = 50,
    since: Annotated[
        str | None,
        Query(
            description=(
                "Retornar solo entradas posteriores a este timestamp ISO 8601. "
                "Formato: `YYYY-MM-DDTHH:MM:SS`. Ejemplo: `2026-03-27T10:00:00`"
            ),
            example="2026-03-27T10:00:00",
        ),
    ] = None,
):
    """Retorna las transcripciones más recientes de una emisora específica."""
    _require_station(station_id)
    entries = manager.storage().recent(station_id=station_id, limit=limit, since=since)
    return {"station_id": station_id, "count": len(entries), "transcriptions": entries}


# ── SSE — Stream en tiempo real ───────────────────────────────────────────────

@router.get(
    "/stream",
    summary="Stream SSE de transcripciones en tiempo real (todas las emisoras)",
    response_class=StreamingResponse,
)
async def sse_all():
    """
    Server-Sent Events: recibe transcripciones de todas las emisoras en tiempo real.

    Conectar con EventSource en JavaScript:
    ```js
    const es = new EventSource('/radio/stream');
    es.onmessage = e => console.log(JSON.parse(e.data));
    ```

    Cada evento tiene la estructura:
    ```json
    {
      "station_id": "tropicana_cali",
      "station_name": "Tropicana Cali",
      "timestamp": "2026-03-27T10:30:00Z",
      "chunk_start": 0.0,
      "chunk_end": 5.2,
      "text": "buenos días Cali, son las 10 de la mañana...",
      "confidence": -0.35
    }
    ```
    """
    return StreamingResponse(
        _sse_generator(station_id=None),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Deshabilitar buffer en nginx
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/stream/{station_id}",
    summary="Stream SSE de una emisora específica",
    response_class=StreamingResponse,
)
async def sse_station(station_id: Annotated[str, _STATION_ID_PARAM]):
    """SSE filtrado para una sola emisora. Misma estructura que /radio/stream."""
    _require_station(station_id)
    return StreamingResponse(
        _sse_generator(station_id=station_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
