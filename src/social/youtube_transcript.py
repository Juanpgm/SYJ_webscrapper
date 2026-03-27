from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

from youtube_transcript_api import YouTubeTranscriptApi

log = logging.getLogger(__name__)


def extract_video_id(video_url: str) -> str | None:
    parsed = urlparse(video_url)
    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/") or None
    query = parse_qs(parsed.query)
    video_ids = query.get("v")
    if video_ids:
        return video_ids[0]
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
        return parts[1]
    return None


def _normalize_lines(chunks: list[str]) -> str:
    normalized: list[str] = []
    for chunk in chunks:
        text = " ".join(str(chunk).split())
        if text:
            normalized.append(text)
    return " ".join(normalized).strip()


class YouTubeTranscriptService:
    def __init__(
        self,
        *,
        languages: list[str] | None = None,
        enable_audio_fallback: bool = True,
        whisper_model: str = "tiny",
        whisper_device: str = "auto",
        whisper_compute_type: str = "int8",
        download_root: str | None = None,
    ) -> None:
        self.languages = tuple(languages or ["es", "es-419", "en"])
        self.enable_audio_fallback = enable_audio_fallback
        self.whisper_model_name = whisper_model
        self.whisper_device = whisper_device
        self.whisper_compute_type = whisper_compute_type
        self.download_root = download_root
        self._api = YouTubeTranscriptApi()
        self._whisper_model = None

    def fetch(self, video_url: str) -> dict[str, str | None]:
        video_id = extract_video_id(video_url)
        if not video_id:
            return {"text": "", "source": None}

        transcript_text = self._fetch_captions(video_id)
        if transcript_text:
            return {"text": transcript_text, "source": "captions"}

        if self.enable_audio_fallback:
            transcript_text = self._transcribe_from_audio(video_url)
            if transcript_text:
                return {"text": transcript_text, "source": "whisper"}

        return {"text": "", "source": None}

    def _fetch_captions(self, video_id: str) -> str:
        try:
            transcript = self._api.fetch(video_id, languages=self.languages, preserve_formatting=False)
            raw_data = transcript.to_raw_data()
            return _normalize_lines([item.get("text", "") for item in raw_data if isinstance(item, dict)])
        except Exception as exc:
            log.debug("No transcript via captions for %s: %s", video_id, exc)
            return ""

    def _transcribe_from_audio(self, video_url: str) -> str:
        try:
            with TemporaryDirectory(dir=self.download_root) as temp_dir:
                audio_path = self._download_audio(video_url, Path(temp_dir))
                if audio_path is None:
                    return ""
                model = self._get_whisper_model()
                segments, _info = model.transcribe(
                    str(audio_path),
                    language="es",
                    vad_filter=True,
                    beam_size=1,
                )
                return _normalize_lines([segment.text for segment in segments])
        except Exception as exc:
            log.debug("Whisper fallo para %s: %s", video_url, exc)
            return ""

    def _download_audio(self, video_url: str, temp_dir: Path) -> Path | None:
        from yt_dlp import YoutubeDL

        output_template = str(temp_dir / "%(id)s.%(ext)s")
        options = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "outtmpl": output_template,
            "retries": 2,
            "fragment_retries": 2,
            "cachedir": False,
        }
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(video_url, download=True)
            requested_downloads = info.get("requested_downloads") or []
            if requested_downloads:
                candidate = requested_downloads[0].get("filepath") or requested_downloads[0].get("filename")
                if candidate and Path(candidate).exists():
                    return Path(candidate)
            prepared = Path(ydl.prepare_filename(info))
            if prepared.exists():
                return prepared
            for file_path in temp_dir.glob("*"):
                if file_path.is_file():
                    return file_path
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