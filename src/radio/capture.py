"""
Captura de audio continuo desde una URL HLS via ffmpeg.

Genera chunks de audio como numpy arrays (float32, mono, 16kHz)
listos para ser enviados a Whisper.

Requiere: ffmpeg instalado en el sistema y disponible en PATH.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Generator
from typing import Any

import numpy as np

log = logging.getLogger("radio.capture")

SAMPLE_RATE = 16_000  # Hz requerido por Whisper


def _build_ffmpeg_cmd(hls_url: str) -> list[str]:
    """
    Construye el comando ffmpeg para capturar audio continuo como PCM s16le.

    Flags de reconexión: permiten que ffmpeg se reconecte automáticamente
    si la URL HLS rota (Google lo hace cada ~5 min en streams largos).
    """
    return [
        "ffmpeg",
        # Reconexión automática ante caídas de red
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "10",
        # Input
        "-i", hls_url,
        # Output: PCM signed 16-bit little-endian, mono, 16kHz → stdout
        "-f", "s16le",
        "-ar", str(SAMPLE_RATE),
        "-ac", "1",
        "-loglevel", "error",
        "pipe:1",
    ]


def audio_chunks(
    hls_url: str,
    chunk_duration: int = 30,
) -> Generator[np.ndarray, None, None]:
    """
    Genera chunks de audio como numpy float32 desde un stream HLS.

    Args:
        hls_url: URL directa del stream de audio (m3u8 u otro formato soportado por ffmpeg).
        chunk_duration: Duración en segundos de cada chunk generado.

    Yields:
        numpy.ndarray shape (N,) dtype float32, normalizado [-1, 1].

    Raises:
        RuntimeError: Si ffmpeg no se puede iniciar o el stream se corta.
    """
    bytes_per_sample = 2  # int16 = 2 bytes
    chunk_bytes = SAMPLE_RATE * chunk_duration * bytes_per_sample

    cmd = _build_ffmpeg_cmd(hls_url)
    log.debug("Iniciando ffmpeg: %s", " ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=chunk_bytes * 2,
    )

    buffer = b""
    try:
        while True:
            # Leer hasta completar un chunk o EOF
            remaining = chunk_bytes - len(buffer)
            chunk = proc.stdout.read(remaining)  # type: ignore[union-attr]

            if not chunk:
                # ffmpeg terminó (stream cortado o error)
                if buffer:
                    # Emitir lo que quedó en buffer
                    audio = np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
                    yield audio
                break

            buffer += chunk

            if len(buffer) >= chunk_bytes:
                audio = np.frombuffer(buffer[:chunk_bytes], dtype=np.int16).astype(np.float32) / 32768.0
                yield audio
                buffer = buffer[chunk_bytes:]

    except Exception as exc:
        log.error("Error leyendo audio de ffmpeg: %s", exc)
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        stderr_out = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
        if stderr_out:
            log.debug("ffmpeg stderr: %s", stderr_out)
