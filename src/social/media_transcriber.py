from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

log = logging.getLogger(__name__)


def _normalize_text(chunks: list[str]) -> str:
    values: list[str] = []
    for chunk in chunks:
        text = " ".join(str(chunk).split())
        if text:
            values.append(text)
    return " ".join(values).strip()


class MediaTranscriber:
    def __init__(
        self,
        *,
        whisper_model: str = "tiny",
        whisper_device: str = "auto",
        whisper_compute_type: str = "int8",
        timeout_seconds: int = 45,
        max_bytes: int = 80 * 1024 * 1024,
    ) -> None:
        self.whisper_model_name = whisper_model
        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self._whisper_model = None

    def transcribe_media_url(self, media_url: str, *, language: str = "es") -> str:
        if not media_url:
            return ""
        try:
            with TemporaryDirectory() as temp_dir:
                media_path = self._download_media(media_url, Path(temp_dir))
                if media_path is None:
                    return ""
                model = self._get_whisper_model()
                segments, _info = model.transcribe(
                    str(media_path),
                    language=language,
                    vad_filter=True,
                    beam_size=1,
                )
                return _normalize_text([segment.text for segment in segments])
        except Exception as exc:
            log.debug("Fallo transcribiendo media %s: %s", media_url, exc)
            return ""

    def _download_media(self, media_url: str, temp_dir: Path) -> Path | None:
        target = temp_dir / "media.mp4"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://www.instagram.com/",
        }
        received = 0
        with requests.get(media_url, stream=True, timeout=self.timeout_seconds, headers=headers) as response:
            response.raise_for_status()
            with target.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > self.max_bytes:
                        break
                    stream.write(chunk)

        if target.exists() and target.stat().st_size > 0:
            return target
        return None

    def _get_whisper_model(self):
        if self._whisper_model is None:
            from faster_whisper import WhisperModel

            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device=self.whisper_device,
                compute_type=self.whisper_compute_type,
            )
        return self._whisper_model