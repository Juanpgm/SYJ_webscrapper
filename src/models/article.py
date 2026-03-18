from pydantic import BaseModel, Field, HttpUrl


class CommentRecord(BaseModel):
    fecha_hora: str | None = None
    usuario: str | None = None
    texto: str


class ArticleRecord(BaseModel):
    fecha_obtencion: str = Field(..., description="dd/mm/aaaa")
    fecha_publicacion: str = Field(..., description="dd/mm/aaaa")
    fuente: str
    raw_text: str
    snippet_text: str
    title: str = ""
    url_noticia: HttpUrl
    source_type: str = "news"
    platform: str | None = None
    content_kind: str | None = None
    author_name: str | None = None
    author_handle: str | None = None
    canonical_id: str | None = None
    description_text: str | None = None
    transcript_text: str | None = None
    transcript_source: str | None = None
    comments_text: list[str] = Field(default_factory=list)
    comments: list[CommentRecord] = Field(default_factory=list)
    n_comments: int = 0
    barrio_detectado: str | None = None
    comuna_detectada: str | None = None
    lugares_mencionados: list[str] = Field(default_factory=list)
    sentimiento_score: float | None = None
    sentimiento_label: str | None = None
    tipo_incidente: list[str] = Field(default_factory=list)
    nlp_provider: str | None = None
