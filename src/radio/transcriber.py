"""
Transcriptor compartido basado en faster-whisper.

Un único modelo es cargado lazily y compartido por todos los workers
de emisoras (con lock para evitar concurrencia en CPU).
El VAD integrado de Whisper descarta automáticamente música y silencios.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

log = logging.getLogger("radio.transcriber")

_model: "WhisperModel | None" = None
_init_lock = threading.Lock()
_infer_lock = threading.Lock()

_model_cfg: dict[str, str] = {
    "model": "small",
    "device": "cpu",
    "compute_type": "int8",
}


def configure(model: str = "small", device: str = "cpu", compute_type: str = "int8") -> None:
    """Aplica configuración antes de la primera carga del modelo."""
    global _model_cfg
    _model_cfg = {"model": model, "device": device, "compute_type": compute_type}


def _get_model() -> "WhisperModel":
    global _model
    if _model is None:
        with _init_lock:
            if _model is None:
                from faster_whisper import WhisperModel

                log.info(
                    "Cargando Whisper '%s' [%s/%s]...",
                    _model_cfg["model"],
                    _model_cfg["device"],
                    _model_cfg["compute_type"],
                )
                _model = WhisperModel(
                    _model_cfg["model"],
                    device=_model_cfg["device"],
                    compute_type=_model_cfg["compute_type"],
                )
                log.info("Modelo Whisper listo.")
    return _model


def transcribe(
    audio: np.ndarray,
    *,
    language: str = "es",
    vad_filter: bool = True,
    vad_min_silence_ms: int = 500,
) -> list[dict[str, Any]]:
    """
    Transcribe un chunk de audio.

    Args:
        audio: numpy float32 array, mono, 16kHz.
        language: código de idioma ISO 639-1.
        vad_filter: activa el VAD de Silero integrado en Whisper.
        vad_min_silence_ms: silencio mínimo para separar segmentos (ms).

    Returns:
        Lista de dicts {start, end, text, confidence}.
        Lista vacía si el chunk es solo música/silencio.
    """
    if audio.size == 0:
        return []

    model = _get_model()

    with _infer_lock:
        segments_iter, _info = model.transcribe(
            audio,
            language=language,
            vad_filter=vad_filter,
            vad_parameters={"min_silence_duration_ms": vad_min_silence_ms},
            beam_size=2,
            condition_on_previous_text=False,
        )
        results: list[dict[str, Any]] = []
        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue
            results.append(
                {
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text,
                    "confidence": round(seg.avg_logprob, 4),
                }
            )

    return results
