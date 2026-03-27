from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ScrapeRunRequest(BaseModel):
    """Parámetros para ejecutar el pipeline completo de scraping."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "fecha_desde": "01/03/2026",
                "fecha_hasta": "27/03/2026",
                "fuentes": ["el_pais_cali", "q_hubo"],
                "force_reprocess": False,
                "html_only": False,
                "include_social": False,
                "social_only": False,
            }
        }
    )

    fecha_desde: str | None = Field(
        None,
        description=(
            "Fecha de inicio del rango a scrapear, formato **DD/MM/YYYY**. "
            "Si se omite, el scraper usa la fecha configurada por defecto en `scraper_config.yaml`. "
            "Ejemplo: `01/03/2026`"
        ),
        examples=["01/03/2026"],
    )
    fecha_hasta: str | None = Field(
        None,
        description=(
            "Fecha de fin del rango a scrapear, formato **DD/MM/YYYY**. "
            "Si se omite, se usa la fecha actual. "
            "Ejemplo: `27/03/2026`"
        ),
        examples=["27/03/2026"],
    )
    fuentes: list[str] | None = Field(
        None,
        description=(
            "Lista de IDs de fuentes de noticias a incluir. "
            "Si se omite (`null`), se procesan **todas** las fuentes configuradas. "
            "Obtén los IDs disponibles con `GET /sources` (campo `id` de cada fuente). "
            "Ejemplo: `[\"el_pais_cali\", \"q_hubo\"]`"
        ),
        examples=[["el_pais_cali", "q_hubo"]],
    )
    force_reprocess: bool = Field(
        False,
        description=(
            "Si es `true`, re-descarga y re-parsea artículos que ya existen en disco. "
            "Útil para forzar actualización de contenido ya scrapeado. "
            "Por defecto `false` (solo procesa artículos nuevos)."
        ),
    )
    html_only: bool = Field(
        False,
        description=(
            "Si es `true`, solo descarga el HTML sin pasar por el parser de artículos. "
            "Útil para depuración o cuando se quiere inspeccionar el HTML crudo antes de parsear. "
            "Por defecto `false`."
        ),
    )
    include_social: bool = Field(
        False,
        description=(
            "Si es `true`, también ejecuta los conectores de redes sociales además de las fuentes de noticias. "
            "No es compatible con `social_only=true`. Por defecto `false`."
        ),
    )
    social_only: bool = Field(
        False,
        description=(
            "Si es `true`, ejecuta **únicamente** los conectores de redes sociales, omitiendo fuentes de noticias. "
            "Equivale a llamar `POST /scrape/social`. Por defecto `false`."
        ),
    )


class ScrapeSourceRequest(BaseModel):
    """Parámetros para scrapear una fuente de noticias específica."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "fecha_desde": "01/03/2026",
                "fecha_hasta": "27/03/2026",
                "force_reprocess": False,
                "html_only": False,
            }
        }
    )

    fecha_desde: str | None = Field(
        None,
        description="Fecha de inicio, formato **DD/MM/YYYY**. Ejemplo: `01/03/2026`",
        examples=["01/03/2026"],
    )
    fecha_hasta: str | None = Field(
        None,
        description="Fecha de fin, formato **DD/MM/YYYY**. Si se omite, usa la fecha actual. Ejemplo: `27/03/2026`",
        examples=["27/03/2026"],
    )
    force_reprocess: bool = Field(
        False,
        description="Reprocesar artículos ya existentes en disco. Por defecto `false`.",
    )
    html_only: bool = Field(
        False,
        description="Solo descargar HTML sin parsear. Por defecto `false`.",
    )


class ScrapeSocialRequest(BaseModel):
    """Parámetros para scrapear fuentes de redes sociales."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "fecha_desde": "01/03/2026",
                "fecha_hasta": "27/03/2026",
                "social_ids": None,
                "force_reprocess": False,
            }
        }
    )

    fecha_desde: str | None = Field(
        None,
        description="Fecha de inicio, formato **DD/MM/YYYY**. Ejemplo: `01/03/2026`",
        examples=["01/03/2026"],
    )
    fecha_hasta: str | None = Field(
        None,
        description="Fecha de fin, formato **DD/MM/YYYY**. Si se omite, usa la fecha actual.",
        examples=["27/03/2026"],
    )
    social_ids: list[str] | None = Field(
        None,
        description=(
            "Lista de IDs de conectores sociales a ejecutar. "
            "Si se omite (`null`), se ejecutan **todos** los conectores habilitados. "
            "Obtén los IDs con `GET /social-sources` (campo `id` de cada fuente)."
        ),
        examples=[None],
    )
    force_reprocess: bool = Field(
        False,
        description="Reprocesar entradas sociales ya existentes. Por defecto `false`.",
    )


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class ArticleFilters(BaseModel):
    source: str | None = None
    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
