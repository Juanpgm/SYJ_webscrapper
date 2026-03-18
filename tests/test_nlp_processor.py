from src.nlp.minimal_processor import enrich_payload


def test_enrich_payload_detects_place_sentiment_and_incident() -> None:
    payload = {
        "fecha_obtencion": "18/03/2026",
        "fecha_publicacion": "18/03/2026",
        "fuente": "test",
        "raw_text": "Ataque con explosivos en el MIO de Aguablanca, comuna 13, dejó heridos y temor ciudadano",
        "snippet_text": "Ataque con explosivos en el MIO",
        "title": "Ataque en Aguablanca",
        "url_noticia": "https://example.com/test",
    }

    enriched = enrich_payload(payload)

    assert enriched["barrio_detectado"] == "Aguablanca"
    assert enriched["comuna_detectada"] == "13"
    assert enriched["sentimiento_label"] == "Negativo"
    assert "Explosivos/Terror" in enriched["tipo_incidente"]
    assert enriched["nlp_provider"] == "rules"
