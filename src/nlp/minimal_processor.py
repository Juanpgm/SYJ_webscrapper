from __future__ import annotations

import re
import unicodedata

from src.nlp.ollama_processor import enrich_with_ollama


_BARRIOS = {
    "aguablanca": "Aguablanca",
    "alfonso lopez": "Alfonso Lopez",
    "andres sanin": "Andres Sanin",
    "calipso": "Calipso",
    "caney": "El Caney",
    "centro": "Centro",
    "ciudad jardin": "Ciudad Jardin",
    "floralia": "Floralia",
    "granada": "Granada",
    "lili": "Valle del Lili",
    "melendez": "Melendez",
    "obrero": "Barrio Obrero",
    "pampalinda": "Pampalinda",
    "petecuy": "Petecuy",
    "potrero grande": "Potrero Grande",
    "sameco": "Sameco",
    "san antonio": "San Antonio",
    "siloe": "Siloe",
    "siloe": "Siloe",
    "sucre": "Sucre",
    "terron colorado": "Terron Colorado",
    "union de vivienda": "Union de Vivienda Popular",
    "universidades": "Universidades",
}

_NEGATIVE_WORDS = {
    "homicidio",
    "asesinato",
    "ataque",
    "ataques",
    "explosivo",
    "explosivos",
    "herido",
    "heridos",
    "muerto",
    "muertos",
    "secuestro",
    "extorsion",
    "robo",
    "hurto",
    "balacera",
    "sicariato",
    "terror",
    "inseguridad",
}

_POSITIVE_WORDS = {
    "captura",
    "capturas",
    "incautacion",
    "incauta",
    "prevencion",
    "comunidad",
    "control",
    "seguridad",
    "operativo",
    "rescate",
    "proteccion",
}

_INCIDENT_RULES = {
    "Explosivos/Terror": [r"\bexplosiv", r"\bbomba", r"\batentad", r"\bterror"],
    "Violencia letal": [r"\bhomicid", r"\basesinad", r"\bmuert[oa]s?\b", r"\bsicari"],
    "Secuestro/Extorsion": [r"\bsecuestro", r"\bextors", r"\bvacuna\b"],
    "Crimen organizado": [r"\bnarcotraf", r"\bdisidenc", r"\bgrupo[s]? armad", r"\bmaf"],
    "Delitos patrimoniales": [r"\bhurto", r"\brobo", r"\bestafa", r"\batraco", r"\bfleteo"],
    "Judicial/Control": [r"\bcaptur", r"\bfiscal", r"\bpolicia", r"\boperativo", r"\bincauta"],
    "Convivencia social": [r"\bri[aá]s?\b", r"\bintolerancia", r"\bcomunidad", r"\bvecin"],
}


def _normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFD", text.lower())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _detect_places(text: str) -> tuple[str | None, str | None, list[str]]:
    normalized = _normalize_text(text)
    places: list[str] = []
    barrio_detectado: str | None = None

    for token, label in _BARRIOS.items():
        if token in normalized:
            places.append(label)
            if barrio_detectado is None:
                barrio_detectado = label

    comuna_match = re.search(r"\bcomuna\s+(\d{1,2})\b", normalized)
    comuna_detectada = comuna_match.group(1) if comuna_match else None

    if "mio" in normalized and "MIO" not in places:
        places.append("MIO")

    return barrio_detectado, comuna_detectada, list(dict.fromkeys(places))


def _score_sentiment(text: str) -> tuple[float, str]:
    normalized = _normalize_text(text)
    negative_hits = sum(1 for word in _NEGATIVE_WORDS if word in normalized)
    positive_hits = sum(1 for word in _POSITIVE_WORDS if word in normalized)
    denominator = max(1, negative_hits + positive_hits)
    score = round((positive_hits - negative_hits) / denominator, 3)

    if score < -0.05:
        return score, "Negativo"
    if score > 0.05:
        return score, "Positivo"
    return score, "Neutro"


def _detect_incidents(text: str) -> list[str]:
    normalized = _normalize_text(text)
    matches: list[str] = []
    for label, patterns in _INCIDENT_RULES.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            matches.append(label)
    return matches


def enrich_payload(payload: dict, app_cfg: dict | None = None) -> dict:
    title = str(payload.get("title") or "").strip()
    description_text = str(payload.get("description_text") or "").strip()
    transcript_text = str(payload.get("transcript_text") or "").strip()
    raw_text = str(payload.get("raw_text") or "").strip()
    snippet = str(payload.get("snippet_text") or "").strip()

    content = " ".join(part for part in [title, description_text, transcript_text, raw_text, snippet] if part).strip()
    if not content:
        return payload

    barrio_detectado, comuna_detectada, lugares_mencionados = _detect_places(content)
    sentimiento_score, sentimiento_label = _score_sentiment(content)
    tipo_incidente = _detect_incidents(content)

    enriched = dict(payload)
    if not title:
        enriched["title"] = content[:120].strip()
    enriched["barrio_detectado"] = barrio_detectado
    enriched["comuna_detectada"] = comuna_detectada
    enriched["lugares_mencionados"] = lugares_mencionados
    enriched["sentimiento_score"] = sentimiento_score
    enriched["sentimiento_label"] = sentimiento_label
    enriched["tipo_incidente"] = tipo_incidente

    llm_enriched = enrich_with_ollama(enriched, app_cfg)
    if isinstance(llm_enriched, dict):
        for field in (
            "barrio_detectado",
            "comuna_detectada",
            "lugares_mencionados",
            "sentimiento_score",
            "sentimiento_label",
            "tipo_incidente",
            "nlp_provider",
        ):
            value = llm_enriched.get(field)
            if value not in (None, [], ""):
                enriched[field] = value
    else:
        enriched["nlp_provider"] = "rules"
    return enriched
