"""
Watcher: detecta si un canal de YouTube tiene un stream activo
y extrae la URL directa del flujo de audio HLS.

Usa yt-dlp (ya disponible en el proyecto) sin descarga de archivos.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("radio.watcher")


def _ydl_quiet_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "cachedir": False,
        "skip_download": True,
    }


def check_live(channel_url: str) -> bool:
    """
    Retorna True si el canal tiene una transmisión en vivo activa.
    channel_url debe apuntar a youtube.com/@Handle/live o al ID del stream.
    """
    from yt_dlp import YoutubeDL

    opts = _ydl_quiet_opts()
    opts["format"] = "bestaudio/best"

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if info is None:
                return False
            # Si hay un stream en vivo, is_live=True o live_status='is_live'
            is_live = info.get("is_live") or info.get("live_status") == "is_live"
            return bool(is_live)
    except Exception as exc:
        # yt-dlp lanza excepción cuando no hay stream activo en /live
        log.debug("check_live(%s): %s", channel_url, exc)
        return False


def get_audio_stream_url(channel_url: str) -> str | None:
    """
    Extrae la URL directa del flujo de audio (HLS .m3u8) del stream activo.
    Retorna None si la emisora no está en vivo o si falla la extracción.
    """
    from yt_dlp import YoutubeDL

    opts = _ydl_quiet_opts()
    # bestaudio sin video para minimizar ancho de banda
    opts["format"] = "bestaudio/best"

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(channel_url, download=False)
            if info is None:
                return None

            is_live = info.get("is_live") or info.get("live_status") == "is_live"
            if not is_live:
                log.debug("get_audio_stream_url: no es live → %s", channel_url)
                return None

            # URL directa del mejor formato de audio
            url = info.get("url")
            if url:
                return url

            # Formatos alternativos (lista de candidatos)
            for fmt in info.get("formats", []):
                if fmt.get("acodec") != "none" and fmt.get("vcodec") in (None, "none"):
                    candidate = fmt.get("url")
                    if candidate:
                        return candidate

            # Fallback: URL del primer formato disponible
            formats = info.get("formats", [])
            if formats:
                return formats[-1].get("url")

    except Exception as exc:
        log.warning("get_audio_stream_url(%s) falló: %s", channel_url, exc)

    return None
