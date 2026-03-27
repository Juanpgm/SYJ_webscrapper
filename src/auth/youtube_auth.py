"""
Gestión de autenticación de YouTube para yt-dlp.

Dos capas de auth:
  1. PO Token (Proof of Origin) — generado automáticamente via Node.js
     Funciona para contenido público sin necesidad de cuenta.

  2. Cookies de sesión (cookies.txt Netscape) — exportadas del browser
     Requeridas para contenido restringido, con restricción de edad, o privado.

Uso:
    opts = get_ydl_auth_opts()
    with YoutubeDL({**opts, 'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("auth.youtube")

ROOT = Path(__file__).resolve().parent.parent.parent
_COOKIES_PATH = ROOT / "data" / "yt_cookies.txt"
_TOKENS_CACHE = ROOT / "data" / "yt_po_token_cache.json"
_NODE_BIN = "C:/nvm4w/nodejs/youtube-po-token-generator.cmd"

# PO token se renueva cada 5 minutos (expiran en ~6 min según yt-dlp docs)
_PO_TOKEN_TTL = 300

_lock = threading.Lock()
_token_cache: dict[str, Any] = {}


# ─── PO Token ────────────────────────────────────────────────────────────────

def _generate_po_token() -> dict[str, str] | None:
    """
    Llama al generador Node.js y retorna {visitorData, poToken}.
    Retorna None si el binario no está disponible.
    """
    node_bin = Path(_NODE_BIN)
    if not node_bin.exists():
        # Intentar desde PATH
        try:
            result = subprocess.run(
                ["youtube-po-token-generator"],
                capture_output=True, text=True, timeout=45,
            )
        except FileNotFoundError:
            log.warning("youtube-po-token-generator no encontrado. Instala con: npm install -g youtube-po-token-generator")
            return None
    else:
        try:
            result = subprocess.run(
                [str(node_bin)],
                capture_output=True, text=True, timeout=45,
            )
        except Exception as exc:
            log.warning("Error generando PO token: %s", exc)
            return None

    if result.returncode != 0 or not result.stdout.strip():
        log.warning("PO token generator falló (rc=%d): %s", result.returncode, result.stderr[:200])
        return None

    try:
        tokens = json.loads(result.stdout.strip())
        log.info("PO Token generado correctamente.")
        return tokens
    except json.JSONDecodeError as exc:
        log.warning("Error parseando PO tokens: %s | stdout: %s", exc, result.stdout[:200])
        return None


def get_po_token(force_refresh: bool = False) -> dict[str, str] | None:
    """Retorna tokens cacheados o genera nuevos si expiraron."""
    with _lock:
        now = time.time()
        cached = _token_cache.get("tokens")
        generated_at = _token_cache.get("generated_at", 0)

        if not force_refresh and cached and (now - generated_at) < _PO_TOKEN_TTL:
            return cached

        tokens = _generate_po_token()
        if tokens:
            _token_cache["tokens"] = tokens
            _token_cache["generated_at"] = now
            # Persistir para depuración
            try:
                _TOKENS_CACHE.parent.mkdir(parents=True, exist_ok=True)
                _TOKENS_CACHE.write_text(
                    json.dumps({**tokens, "generated_at": now}, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass
        return tokens


# ─── Cookies ─────────────────────────────────────────────────────────────────

def save_cookies(content: bytes | str) -> Path:
    """
    Guarda el contenido del cookies.txt en disco.
    Acepta bytes o str en formato Netscape (exportado por extensiones de browser).
    """
    _COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        _COOKIES_PATH.write_bytes(content)
    else:
        _COOKIES_PATH.write_text(content, encoding="utf-8")
    log.info("Cookies guardadas en %s", _COOKIES_PATH)
    return _COOKIES_PATH


def cookies_exist() -> bool:
    return _COOKIES_PATH.exists() and _COOKIES_PATH.stat().st_size > 100


def cookies_info() -> dict[str, Any]:
    if not cookies_exist():
        return {"exists": False}
    stat = _COOKIES_PATH.stat()
    # Contar líneas con cookies de .youtube.com
    try:
        lines = _COOKIES_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
        yt_cookies = [l for l in lines if "youtube.com" in l and not l.startswith("#")]
        return {
            "exists": True,
            "path": str(_COOKIES_PATH),
            "size_kb": round(stat.st_size / 1024, 1),
            "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
            "youtube_cookie_entries": len(yt_cookies),
        }
    except Exception:
        return {"exists": True, "path": str(_COOKIES_PATH)}


def clear_cookies() -> None:
    if _COOKIES_PATH.exists():
        _COOKIES_PATH.unlink()
        log.info("Cookies eliminadas.")


# ─── yt-dlp options builder ──────────────────────────────────────────────────

def get_ydl_auth_opts(force_refresh_token: bool = False) -> dict[str, Any]:
    """
    Retorna el dict de opciones de autenticación para YoutubeDL.

    Prioridad:
      1. Cookies (si existen) + PO Token
      2. Solo PO Token (contenido público)
      3. Sin auth (puede fallar en contenido restringido)
    """
    opts: dict[str, Any] = {}

    # Siempre añadir PO token si disponible (mejora la tasa de éxito)
    tokens = get_po_token(force_refresh=force_refresh_token)
    if tokens:
        visitor = tokens.get("visitorData", "")
        pot = tokens.get("poToken", "")
        if visitor and pot:
            opts["extractor_args"] = {
                "youtube": {
                    "po_token": [f"GVS+{pot}"],
                    "visitor_data": [visitor],
                }
            }
            log.debug("PO Token inyectado en opts.")

    # Cookies si existen (necesarias para contenido restringido)
    if cookies_exist():
        opts["cookiefile"] = str(_COOKIES_PATH)
        log.debug("Cookies inyectadas desde %s", _COOKIES_PATH)

    return opts


def auth_status() -> dict[str, Any]:
    """Retorna el estado completo de autenticación."""
    tokens = _token_cache.get("tokens")
    generated_at = _token_cache.get("generated_at", 0)
    age = int(time.time() - generated_at) if generated_at else None

    return {
        "po_token": {
            "available": tokens is not None,
            "age_seconds": age,
            "expired": age is not None and age > _PO_TOKEN_TTL,
            "ttl_seconds": _PO_TOKEN_TTL,
            "generator_path": _NODE_BIN,
        },
        "cookies": cookies_info(),
        "recommendation": (
            "OK — cookies + PO token activos" if (cookies_exist() and tokens)
            else "PARCIAL — solo PO token (videos públicos)" if tokens
            else "PARCIAL — solo cookies (sin PO token)" if cookies_exist()
            else "SIN AUTH — sube cookies.txt via POST /auth/youtube/cookies"
        ),
    }
