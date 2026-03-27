"""
Transcripción bajo demanda de cualquier URL de YouTube.

Endpoint:
  POST /transcribe/youtube

Pipeline:
  1. Auth: inyecta PO Token (automático) + cookies si están disponibles
  2. yt-dlp: descarga mejor audio disponible
  3. faster-whisper + VAD: transcribe filtrando música/silencio
  4. Retorna transcripción + métricas detalladas de rendimiento

Métricas incluidas:
  - Tiempos por fase (descarga, carga modelo, inferencia)
  - Factor de tiempo real (audio_duration / transcription_time)
  - Uso de memoria RSS (baseline vs pico)
  - CPU promedio y pico durante la transcripción
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.auth.youtube_auth import get_ydl_auth_opts

router = APIRouter(prefix="/transcribe", tags=["transcripción"])

_PROC = psutil.Process(os.getpid())


# ── Request model ─────────────────────────────────────────────────────────────

class TranscribeRequest(BaseModel):
    """Parámetros para transcribir audio de un video de YouTube."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://www.youtube.com/watch?v=X54nbYSoH-A",
                "model": "small",
                "language": "es",
                "device": "cpu",
                "compute_type": "int8",
                "vad_filter": True,
                "beam_size": 2,
                "force_refresh_token": False,
            }
        }
    )

    url: str = Field(
        ...,
        description=(
            "URL completa del video de YouTube. Acepta: videos normales, Shorts, streams en vivo, y playlists "
            "(solo transcribe el primero). "
            "Ejemplo: `https://www.youtube.com/watch?v=X54nbYSoH-A`"
        ),
        examples=["https://www.youtube.com/watch?v=X54nbYSoH-A"],
    )
    model: str = Field(
        "small",
        description=(
            "Tamaño del modelo Whisper a usar. Trade-off velocidad vs precisión: "
            "`tiny` (más rápido, menos preciso) → `base` → `small` → `medium` → `large-v3` (más lento, más preciso). "
            "Para español se recomienda `small` o `medium`. En CPU usar `tiny` o `base` para respuesta rápida."
        ),
        examples=["small"],
    )
    language: str = Field(
        "es",
        description=(
            "Código ISO 639-1 del idioma hablado en el audio. "
            "Especificarlo mejora la precisión y velocidad vs auto-detección. "
            "Ejemplos: `es` (español), `en` (inglés), `pt` (portugués)."
        ),
        examples=["es"],
    )
    device: str = Field(
        "cpu",
        description=(
            "Dispositivo de inferencia. `cpu` funciona en cualquier máquina. "
            "`cuda` requiere GPU NVIDIA con CUDA instalado (mucho más rápido). "
            "`auto` selecciona GPU si está disponible, sino CPU."
        ),
        examples=["cpu"],
    )
    compute_type: str = Field(
        "int8",
        description=(
            "Precisión numérica del modelo. Afecta velocidad y uso de memoria. "
            "En CPU: `int8` (recomendado, más rápido). "
            "En GPU: `float16` (mejor balance) o `float32` (máxima precisión). "
            "`int16` es un intermedio."
        ),
        examples=["int8"],
    )
    vad_filter: bool = Field(
        True,
        description=(
            "Activar Voice Activity Detection (VAD). "
            "Filtra automáticamente segmentos de música, silencio y ruido de fondo, "
            "mejorando la precisión y reduciendo alucinaciones del modelo. "
            "Recomendado `true` para radio y contenido con música."
        ),
    )
    beam_size: int = Field(
        2,
        ge=1,
        le=10,
        description=(
            "Tamaño del beam search. Mayor valor = más preciso pero más lento. "
            "`1` es greedy decoding (más rápido). `2`–`5` es el rango práctico. "
            "En CPU con modelo `small`, usar `2` para buen balance."
        ),
        examples=[2],
    )
    force_refresh_token: bool = Field(
        False,
        description=(
            "Forzar la regeneración del PO Token de YouTube antes de descargar. "
            "Útil si la descarga falla por autenticación aunque el token ya exista. "
            "Por defecto `false` (reutiliza el token en caché si no ha expirado)."
        ),
    )


# ── CPU sampler ───────────────────────────────────────────────────────────────

class _CpuSampler:
    def __init__(self, interval: float = 0.4) -> None:
        self._interval = interval
        self._samples: list[float] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        _PROC.cpu_percent(interval=None)
        while not self._stop.is_set():
            self._samples.append(_PROC.cpu_percent(interval=None))
            time.sleep(self._interval)

    def start(self) -> "_CpuSampler":
        self._thread.start()
        return self

    def stop(self) -> dict[str, float | int]:
        self._stop.set()
        self._thread.join(timeout=2)
        if not self._samples:
            return {"avg_percent": 0.0, "peak_percent": 0.0, "samples": 0}
        return {
            "avg_percent": round(sum(self._samples) / len(self._samples), 1),
            "peak_percent": round(max(self._samples), 1),
            "samples": len(self._samples),
        }


# ── Audio download ────────────────────────────────────────────────────────────

def _build_ios_opts(auth_opts: dict[str, Any]) -> dict[str, Any]:
    """
    Construye opts para el cliente ios de YouTube.
    - ios bypasea el n-challenge (no necesita JS runtime)
    - ios NO soporta cookies → se excluyen
    - El PO Token para ios usa prefijo 'ios.gvs+' en vez de 'GVS+'
    """
    extractor_args = dict(auth_opts.get("extractor_args", {}))
    yt_args = dict(extractor_args.get("youtube", {}))

    # Convertir GVS+TOKEN → ios.gvs+TOKEN
    gvs_tokens = [t for t in yt_args.get("po_token", []) if t.startswith("GVS+")]
    ios_tokens = [f"ios.gvs+{t[4:]}" for t in gvs_tokens]

    ios_yt_args: dict[str, Any] = {k: v for k, v in yt_args.items() if k != "po_token"}
    ios_yt_args["player_client"] = ["ios"]
    if ios_tokens:
        ios_yt_args["po_token"] = ios_tokens

    # ios no soporta cookiefile — excluirlo
    ios_opts = {k: v for k, v in auth_opts.items() if k not in ("cookiefile", "extractor_args")}
    ios_opts["extractor_args"] = {**extractor_args, "youtube": ios_yt_args}
    return ios_opts


def _download_audio(url: str, temp_dir: Path, auth_opts: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    from yt_dlp import YoutubeDL

    output_template = str(temp_dir / "%(id)s.%(ext)s")
    common_opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "outtmpl": output_template,
        "retries": 3,
        "fragment_retries": 3,
        "cachedir": False,
    }

    # ios bypasea n-challenge pero sus formatos HTTPS requieren token ios nativo →
    # usar HLS m3u8 (234/233) que no necesitan GVS PO token.
    # web+cookies: usa HTTPS dash normal si el n-challenge no es necesario con cookies.
    ios_opts = _build_ios_opts(auth_opts)
    last_error: Exception | None = None
    for attempt_opts, fmt in [
        ({**ios_opts, **common_opts, "format": "234/233/bestaudio[protocol!=https]/bestaudio/best"}, "ios-hls"),
        ({**auth_opts, **common_opts, "format": "140/251/bestaudio/best"}, "web+cookies"),
    ]:
        try:
            with YoutubeDL(attempt_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if info is not None:
                break
        except Exception as exc:
            last_error = exc
            continue
    else:
        raise last_error or RuntimeError("yt-dlp no pudo extraer información del video.")

    if info is None:
        raise RuntimeError("yt-dlp no pudo extraer información del video.")

    # Localizar archivo descargado
    for src in [
        ((info.get("requested_downloads") or [{}])[0].get("filepath")),
        ((info.get("requested_downloads") or [{}])[0].get("filename")),
    ]:
        if src and Path(src).exists():
            return Path(src), info

    prepared = Path(YoutubeDL({"quiet": True}).prepare_filename(info))  # type: ignore
    if prepared.exists():
        return prepared, info

    for f in sorted(temp_dir.glob("*")):
        if f.is_file():
            return f, info

    raise RuntimeError("No se encontró el archivo de audio descargado.")


def _bytes_to_mb(b: int) -> float:
    return round(b / (1024 ** 2), 2)


def _fmt_duration(seconds: int | float) -> str:
    if not seconds:
        return "0:00"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ── Core pipeline ─────────────────────────────────────────────────────────────

def run_transcription(req: TranscribeRequest) -> dict[str, Any]:
    overall_start = time.perf_counter()
    timeline: dict[str, Any] = {}

    mem_before = _PROC.memory_info().rss

    # ── Fase 0: Auth opts ────────────────────────────────────────────────
    t_auth = time.perf_counter()
    auth_opts = get_ydl_auth_opts(force_refresh_token=req.force_refresh_token)
    timeline["auth_opts_s"] = round(time.perf_counter() - t_auth, 3)

    auth_used = {
        "po_token": "extractor_args" in auth_opts,
        "cookies": "cookiefile" in auth_opts,
    }

    with TemporaryDirectory() as tmp:
        # ── Fase 1: Descarga audio ───────────────────────────────────────
        t_dl = time.perf_counter()
        try:
            audio_path, video_info = _download_audio(req.url, Path(tmp), auth_opts)
        except Exception as exc:
            err = str(exc)
            # Dar contexto útil si es error de bot/cookies
            if "Sign in" in err or "bot" in err.lower():
                raise RuntimeError(
                    "YouTube bloqueó la descarga. "
                    "Sube tus cookies via POST /auth/youtube/cookies y vuelve a intentarlo. "
                    f"Detalle: {err}"
                )
            raise RuntimeError(f"Error descargando audio: {err}")

        audio_size_mb = _bytes_to_mb(audio_path.stat().st_size)
        timeline["download_s"] = round(time.perf_counter() - t_dl, 3)

        # ── Fase 2: Cargar modelo Whisper ────────────────────────────────
        t_model = time.perf_counter()
        from faster_whisper import WhisperModel
        model = WhisperModel(req.model, device=req.device, compute_type=req.compute_type)
        timeline["model_load_s"] = round(time.perf_counter() - t_model, 3)

        # ── Fase 3: Transcripción ────────────────────────────────────────
        t_trans = time.perf_counter()
        cpu_sampler = _CpuSampler(interval=0.4).start()

        segments_iter, detect_info = model.transcribe(
            str(audio_path),
            language=req.language,
            vad_filter=req.vad_filter,
            vad_parameters={"min_silence_duration_ms": 500},
            beam_size=req.beam_size,
            condition_on_previous_text=True,
            word_timestamps=False,
        )

        segments: list[dict[str, Any]] = []
        full_parts: list[str] = []

        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue
            segments.append({
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": text,
                "confidence": round(seg.avg_logprob, 4),
                "no_speech_prob": round(seg.no_speech_prob, 4),
            })
            full_parts.append(text)

        cpu_stats = cpu_sampler.stop()
        timeline["transcription_s"] = round(time.perf_counter() - t_trans, 3)

    # ── Métricas finales ─────────────────────────────────────────────────
    mem_after = _PROC.memory_info().rss
    timeline["total_s"] = round(time.perf_counter() - overall_start, 3)

    audio_duration = video_info.get("duration") or 0
    trans_s = timeline.get("transcription_s", 0)
    realtime_factor = round(audio_duration / trans_s, 2) if trans_s > 0 and audio_duration > 0 else None

    full_text = " ".join(full_parts)
    word_count = len(full_text.split()) if full_text else 0

    return {
        # ── Transcripción ────────────────────────────────────────────────
        "transcript": {
            "full_text": full_text,
            "segments": segments,
            "segments_count": len(segments),
            "word_count": word_count,
            "language_requested": req.language,
            "language_detected": getattr(detect_info, "language", req.language),
            "language_probability": round(getattr(detect_info, "language_probability", 0.0), 4),
        },
        # ── Metadatos del video ──────────────────────────────────────────
        "video": {
            "title": video_info.get("title"),
            "channel": video_info.get("channel") or video_info.get("uploader"),
            "duration_s": audio_duration,
            "duration_human": _fmt_duration(audio_duration),
            "url": req.url,
            "video_id": video_info.get("id"),
            "upload_date": video_info.get("upload_date"),
            "view_count": video_info.get("view_count"),
            "audio_format": video_info.get("acodec"),
            "audio_bitrate_kbps": video_info.get("abr"),
        },
        # ── Métricas de rendimiento ──────────────────────────────────────
        "metrics": {
            "time": {
                **timeline,
                "realtime_factor": realtime_factor,
                "note": "realtime_factor > 1 = más rápido que el audio real" if realtime_factor else "",
            },
            "memory": {
                "baseline_mb": _bytes_to_mb(mem_before),
                "after_mb": _bytes_to_mb(mem_after),
                "delta_mb": _bytes_to_mb(mem_after - mem_before),
                "audio_file_mb": audio_size_mb,
            },
            "cpu": cpu_stats,
            "model": {
                "name": req.model,
                "device": req.device,
                "compute_type": req.compute_type,
                "beam_size": req.beam_size,
                "vad_filter": req.vad_filter,
            },
            "auth": auth_used,
        },
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post(
    "/youtube",
    summary="Transcribir video de YouTube con métricas de rendimiento",
)
def transcribe_youtube(req: TranscribeRequest) -> dict[str, Any]:
    """
    Descarga el audio de cualquier URL de YouTube y lo transcribe con faster-whisper.

    **Auth automático:**
    - Genera PO Token via Node.js para contenido público
    - Usa cookies.txt si están cargadas (necesario para videos restringidos)
    - Si falla por auth, ve a `POST /auth/youtube/cookies`

    **VAD integrado:** filtra automáticamente música y silencios.

    **Métricas retornadas:**
    - `metrics.time.download_s` — tiempo de descarga de audio
    - `metrics.time.model_load_s` — carga del modelo Whisper
    - `metrics.time.transcription_s` — inferencia pura
    - `metrics.time.total_s` — tiempo total de punta a punta
    - `metrics.time.realtime_factor` — veces más rápido que el audio real
    - `metrics.memory.delta_mb` — incremento de memoria RSS
    - `metrics.cpu.avg_percent` / `metrics.cpu.peak_percent`
    """
    try:
        return run_transcription(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error inesperado: {exc}")
