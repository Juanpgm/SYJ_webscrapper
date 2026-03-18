from datetime import datetime

from src.models.article import ArticleRecord


def validate_article_payload(payload: dict) -> ArticleRecord:
    _validate_ddmmyyyy(payload.get("fecha_obtencion", ""))
    _validate_ddmmyyyy(payload.get("fecha_publicacion", ""))
    return ArticleRecord(
        fecha_obtencion=payload["fecha_obtencion"],
        fecha_publicacion=payload["fecha_publicacion"],
        fuente=payload["fuente"],
        raw_text=payload["raw_text"],
        snippet_text=payload["snippet_text"],
        title=payload.get("title", ""),
        url_noticia=payload["url_noticia"],
        source_type=payload.get("source_type", "news"),
        platform=payload.get("platform"),
        content_kind=payload.get("content_kind"),
        author_name=payload.get("author_name"),
        author_handle=payload.get("author_handle"),
        canonical_id=payload.get("canonical_id"),
        description_text=payload.get("description_text"),
        transcript_text=payload.get("transcript_text"),
        transcript_source=payload.get("transcript_source"),
        comments_text=payload.get("comments_text", []),
        comments=payload.get("comments", []),
        n_comments=int(payload.get("n_comments", len(payload.get("comments", [])))),
        barrio_detectado=payload.get("barrio_detectado"),
        comuna_detectada=payload.get("comuna_detectada"),
        lugares_mencionados=payload.get("lugares_mencionados", []),
        sentimiento_score=payload.get("sentimiento_score"),
        sentimiento_label=payload.get("sentimiento_label"),
        tipo_incidente=payload.get("tipo_incidente", []),
        nlp_provider=payload.get("nlp_provider"),
    )


def _validate_ddmmyyyy(value: str) -> None:
    datetime.strptime(value, "%d/%m/%Y")
