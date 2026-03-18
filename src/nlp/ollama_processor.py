from __future__ import annotations

import json
import os
from typing import Any

import requests


def enrich_with_ollama(payload: dict[str, Any], app_cfg: dict[str, Any] | None) -> dict[str, Any] | None:
    if not app_cfg or not bool(app_cfg.get("use_ollama_nlp", False)):
        return None

    base_url = str(os.getenv("OLLAMA_BASE_URL") or app_cfg.get("ollama_base_url", "http://localhost:11434")).rstrip("/")
    model = str(os.getenv("OLLAMA_MODEL") or app_cfg.get("ollama_model", "llama3.1:8b")).strip()
    timeout_seconds = int(app_cfg.get("ollama_timeout_seconds", 45))
    if not model:
        return None

    content = "\n\n".join(
        part
        for part in [
            str(payload.get("title") or "").strip(),
            str(payload.get("description_text") or "").strip(),
            str(payload.get("transcript_text") or "").strip(),
            str(payload.get("raw_text") or "").strip(),
        ]
        if part
    )
    content = content[:12000].strip()
    if not content:
        return None

    prompt = (
        "Extrae senales de seguridad publica de Cali. Responde solo JSON valido con las llaves: "
        "barrio_detectado, comuna_detectada, lugares_mencionados, sentimiento_score, sentimiento_label, tipo_incidente. "
        "Usa sentimiento_label en Positivo, Negativo o Neutro. Si no sabes un campo, usa null o lista vacia.\n\n"
        f"Texto:\n{content}"
    )

    try:
        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        raw_json = body.get("response", "")
        data = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        if not isinstance(data, dict):
            return None
        return _sanitize_ollama_payload(data)
    except Exception:
        return None


def _sanitize_ollama_payload(data: dict[str, Any]) -> dict[str, Any]:
    places = data.get("lugares_mencionados")
    incidents = data.get("tipo_incidente")
    score = data.get("sentimiento_score")
    if isinstance(places, str):
        places = [places]
    if isinstance(incidents, str):
        incidents = [incidents]
    if isinstance(score, str):
        try:
            score = float(score)
        except Exception:
            score = None
    if isinstance(score, (float, int)):
        score = max(-1.0, min(1.0, float(score)))

    label = data.get("sentimiento_label")
    if isinstance(label, str):
        normalized_label = label.strip().capitalize()
        if normalized_label not in {"Positivo", "Negativo", "Neutro"}:
            normalized_label = "Neutro"
    else:
        normalized_label = None

    return {
        "barrio_detectado": _strip_or_none(data.get("barrio_detectado")),
        "comuna_detectada": _strip_or_none(data.get("comuna_detectada")),
        "lugares_mencionados": [_strip_or_none(item) for item in places or [] if _strip_or_none(item)],
        "sentimiento_score": score,
        "sentimiento_label": normalized_label,
        "tipo_incidente": [_strip_or_none(item) for item in incidents or [] if _strip_or_none(item)],
        "nlp_provider": "ollama",
    }


def _strip_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None