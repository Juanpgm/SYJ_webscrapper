from __future__ import annotations

from typing import Any


_DEFAULT_KEYS: dict[str, Any] = {
    "source_type": "news",
    "platform": None,
    "content_kind": None,
    "author_name": None,
    "author_handle": None,
    "canonical_id": None,
    "description_text": None,
    "transcript_text": None,
    "transcript_source": None,
    "comments_text": [],
    "comments": [],
    "n_comments": 0,
    "barrio_detectado": None,
    "comuna_detectada": None,
    "lugares_mencionados": [],
    "sentimiento_score": None,
    "sentimiento_label": None,
    "tipo_incidente": [],
    "nlp_provider": "rules",
}

_YOUTUBE_OPTIONAL_KEYS = (
    "platform",
    "content_kind",
    "author_name",
    "author_handle",
    "canonical_id",
    "description_text",
    "transcript_text",
    "transcript_source",
)


def normalize_output_payload(payload: dict[str, Any], *, default_source_type: str = "news") -> dict[str, Any]:
    normalized = dict(payload)

    for key, value in _DEFAULT_KEYS.items():
        if key not in normalized or normalized.get(key) is None:
            normalized[key] = value if not isinstance(value, list) else list(value)

    source_type = str(normalized.get("source_type") or default_source_type).strip().lower() or default_source_type
    normalized["source_type"] = source_type

    comments = normalized.get("comments")
    if not isinstance(comments, list):
        comments = []

    clean_comments: list[dict[str, Any]] = []
    for item in comments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("texto") or item.get("comment_content") or "").strip()
        if not text:
            continue
        username = str(item.get("usuario") or item.get("username") or "").strip() or None
        fecha_hora = str(item.get("fecha_hora") or "").strip() or None
        clean_comments.append({"usuario": username, "texto": text, "fecha_hora": fecha_hora})

    comments_text = normalized.get("comments_text")
    if not isinstance(comments_text, list):
        comments_text = []
    clean_comments_text = [str(value).strip() for value in comments_text if str(value).strip()]

    if clean_comments and not clean_comments_text:
        clean_comments_text = [item["texto"] for item in clean_comments]
    elif clean_comments_text and not clean_comments:
        clean_comments = [{"usuario": None, "texto": value, "fecha_hora": None} for value in clean_comments_text]

    normalized["comments"] = clean_comments
    normalized["comments_text"] = clean_comments_text
    normalized["n_comments"] = int(normalized.get("n_comments") or len(clean_comments))
    if normalized["n_comments"] != len(clean_comments):
        normalized["n_comments"] = len(clean_comments)

    normalized["lugares_mencionados"] = [
        str(item).strip() for item in (normalized.get("lugares_mencionados") or []) if str(item).strip()
    ]
    normalized["tipo_incidente"] = [
        str(item).strip() for item in (normalized.get("tipo_incidente") or []) if str(item).strip()
    ]

    for nullable_key in (
        "platform",
        "content_kind",
        "author_name",
        "author_handle",
        "canonical_id",
        "description_text",
        "transcript_text",
        "transcript_source",
        "barrio_detectado",
        "comuna_detectada",
        "sentimiento_label",
        "nlp_provider",
    ):
        value = normalized.get(nullable_key)
        if value is None:
            continue
        text = str(value).strip()
        normalized[nullable_key] = text or None

    score = normalized.get("sentimiento_score")
    if score in (None, ""):
        normalized["sentimiento_score"] = None
    else:
        try:
            normalized["sentimiento_score"] = float(score)
        except Exception:
            normalized["sentimiento_score"] = None

    # Keep these keys for YouTube records, but remove them from other outputs when null.
    if str(normalized.get("platform") or "").lower() != "youtube":
        for key in _YOUTUBE_OPTIONAL_KEYS:
            if normalized.get(key) is None:
                normalized.pop(key, None)

    return normalized