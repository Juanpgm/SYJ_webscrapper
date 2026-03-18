"""Módulo para unificar todos los JSON de data/parsed_json en un único DataFrame."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "parsed_json"


def load_articles_df(parsed_dir: Path | str | None = None) -> pd.DataFrame:
    """Lee todos los archivos .json de *parsed_dir* y retorna un DataFrame unificado.

    Parameters
    ----------
    parsed_dir : Path | str | None
        Directorio con los JSON. Por defecto ``data/parsed_json``.

    Returns
    -------
    pd.DataFrame
        DataFrame con todas las noticias, columnas extra:
        - ``source_file``  : nombre del archivo origen (sin extensión)
        - ``fecha_publicacion_dt`` : datetime parseado de ``fecha_publicacion``
        - ``fecha_obtencion_dt``   : datetime parseado de ``fecha_obtencion``
    """
    parsed_dir = Path(parsed_dir) if parsed_dir else _DEFAULT_DIR

    if not parsed_dir.is_dir():
        raise FileNotFoundError(f"Directorio no encontrado: {parsed_dir}")

    frames: list[pd.DataFrame] = []

    for json_file in sorted(parsed_dir.glob("*.json")):
        try:
            with open(json_file, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("No se pudo leer %s: %s", json_file.name, exc)
            continue

        if not data:
            logger.info("Archivo vacío: %s", json_file.name)
            continue

        df = pd.DataFrame(data)
        df["source_file"] = json_file.stem
        frames.append(df)
        logger.info("Cargado %s — %d registros", json_file.name, len(df))

    if not frames:
        logger.warning("No se encontraron datos en %s", parsed_dir)
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Parsear fechas dd/mm/yyyy → datetime
    for col_src, col_dst in [
        ("fecha_publicacion", "fecha_publicacion_dt"),
        ("fecha_obtencion", "fecha_obtencion_dt"),
    ]:
        if col_src in combined.columns:
            combined[col_dst] = pd.to_datetime(
                combined[col_src], format="%d/%m/%Y", errors="coerce"
            )

    # Eliminar duplicados por URL
    before = len(combined)
    combined.drop_duplicates(subset=["url_noticia"], keep="first", inplace=True)
    dupes = before - len(combined)
    if dupes:
        logger.info("Eliminados %d duplicados por url_noticia", dupes)

    combined.sort_values("fecha_publicacion_dt", ascending=False, inplace=True)
    combined.reset_index(drop=True, inplace=True)

    logger.info(
        "DataFrame final: %d artículos, %d columnas, fuentes: %s",
        len(combined),
        len(combined.columns),
        combined["source_file"].unique().tolist(),
    )

    return combined


# ── Ejecución directa ──────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    df = load_articles_df()
    print(f"\n{'='*60}")
    print(f"Total artículos: {len(df)}")
    print(f"Columnas: {list(df.columns)}")
    print(f"Fuentes:  {df['source_file'].value_counts().to_dict()}")
    print(f"\nRango de fechas: {df['fecha_publicacion_dt'].min()} → {df['fecha_publicacion_dt'].max()}")
    print(f"{'='*60}\n")
    print(df[["source_file", "fecha_publicacion", "title", "url_noticia"]].head(15).to_string())
