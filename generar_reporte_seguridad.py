#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Generador de Reporte de Percepción de Seguridad — Santiago de Cali
===================================================================

Carga datos de Instagram y medios digitales, ejecuta limpieza de texto,
sentiment analysis, clasificación de hechos, detección de lugares y genera
un documento Word profesional dirigido al Secretario de Seguridad y Justicia.

Uso:
    python generar_reporte_seguridad.py
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import unicodedata
from collections import Counter
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import yaml

# ── Visualización ────────────────────────────────────────────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from wordcloud import WordCloud

# ── Machine Learning ─────────────────────────────────────────────────────
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

# ── Word ─────────────────────────────────────────────────────────────────
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

# ═══════════════════════════════════════════════════════════════════════════
# Constants & Config
# ═══════════════════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).resolve().parent
PARSED_DIR = BASE_DIR / "data" / "parsed_json"
TEMPLATE_PATH = BASE_DIR / "reports" / "template" / "Medios digitales.docx"
LOGO_OBSERVATORIO = BASE_DIR / "reports" / "template" / "image2.png"
LOGO_ALCALDIA = BASE_DIR / "reports" / "template" / "image1.png"
CONFIG_PATH = BASE_DIR / "config" / "scraper_config.yaml"
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

TODAY = datetime.now()
TODAY_STR = TODAY.strftime("%Y%m%d")
TODAY_DISPLAY = TODAY.strftime("%d de %B de %Y")

# Ventana temporal para filtrar datos
DATE_WINDOW_DAYS = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("reporte_seguridad")

# ═══════════════════════════════════════════════════════════════════════════
# 1. REGEX Y DICCIONARIOS
# ═══════════════════════════════════════════════════════════════════════════

# Patrón del sistema Instagram: "Descripcion: 269 likes, 15 comments - user el March 24, 2026: ""
IG_SYSTEM_RE = re.compile(
    r'(?:Descripcion:\s*)?'
    r'\d+\s+likes?,\s*\d+\s+comments?\s*-\s*'
    r'[\w._]+\s+el\s+\w+\s+\d{1,2},\s*\d{4}:\s*"?',
    re.IGNORECASE,
)

# Emojis
EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "]+",
    flags=re.UNICODE,
)

# ── Barrios, comunas, corregimientos de Cali (diccionario ampliado) ────
BARRIOS_CALI = {
    "aguablanca": "Aguablanca",
    "alfonso lopez": "Alfonso Lopez",
    "alfonso bonilla": "Alfonso Bonilla Aragón",
    "andres sanin": "Andrés Sanín",
    "antonio narino": "Antonio Nariño",
    "belalcazar": "Belalcázar",
    "bretana": "Bretaña",
    "calima": "Calima",
    "calipso": "Calipso",
    "caney": "El Caney",
    "centro": "Centro",
    "chapinero": "Chapinero",
    "chipichape": "Chipichape",
    "ciudad cordoba": "Ciudad Córdoba",
    "ciudad jardin": "Ciudad Jardín",
    "cristobal colon": "Cristóbal Colón",
    "decepaz": "Decepaz",
    "desepaz": "Desepaz",
    "diamante": "El Diamante",
    "el guabal": "El Guabal",
    "el ingenio": "El Ingenio",
    "el limonar": "El Limonar",
    "el penon": "El Peñón",
    "el poblado": "El Poblado",
    "el retiro": "El Retiro",
    "el vallado": "El Vallado",
    "floralia": "Floralia",
    "flora": "La Flora",
    "granada": "Granada",
    "guabal": "El Guabal",
    "holguines": "Holguines",
    "ingenio": "El Ingenio",
    "la base": "La Base",
    "la flora": "La Flora",
    "la selva": "La Selva",
    "las delicias": "Las Delicias",
    "lili": "Valle del Lili",
    "llano verde": "Llano Verde",
    "los chorros": "Los Chorros",
    "los mangos": "Los Mangos",
    "lourdes": "Lourdes",
    "manuela beltran": "Manuela Beltrán",
    "mariano ramos": "Mariano Ramos",
    "marroquin": "Marroquín",
    "melendez": "Meléndez",
    "menga": "Menga",
    "mojica": "Mojica",
    "navarro": "Navarro",
    "obrero": "Barrio Obrero",
    "olimpico": "Olímpico",
    "pampalinda": "Pampalinda",
    "petecuy": "Petecuy",
    "polvorines": "Polvorines",
    "popular": "Popular",
    "potrero grande": "Potrero Grande",
    "primero de mayo": "Primero de Mayo",
    "sameco": "Sameco",
    "san antonio": "San Antonio",
    "san bosco": "San Bosco",
    "san luis": "San Luis",
    "san pedro": "San Pedro",
    "san vicente": "San Vicente",
    "santa elena": "Santa Elena",
    "santa rosa": "Santa Rosa",
    "santiago de cali": "Santiago de Cali",
    "siloe": "Siloé",
    "sucre": "Sucre",
    "tequendama": "Tequendama",
    "terron colorado": "Terrón Colorado",
    "union de vivienda": "Unión de Vivienda Popular",
    "universidades": "Universidades",
    "vipasa": "Vipasa",
    "villa colombia": "Villa Colombia",
}

CORREGIMIENTOS_CALI = {
    "pance": "Pance",
    "la buitrera": "La Buitrera",
    "montebello": "Montebello",
    "la castilla": "La Castilla",
    "golondrinas": "Golondrinas",
    "felidia": "Felidia",
    "la elvira": "La Elvira",
    "la paz": "La Paz",
    "los andes": "Los Andes",
    "saladito": "El Saladito",
    "villacarmelo": "Villacarmelo",
    "el hormiguero": "El Hormiguero",
    "navarro": "Navarro",
    "la leonera": "La Leonera",
    "pichinde": "Pichindé",
}

COMUNAS_CALI = {f"comuna {i}": f"Comuna {i}" for i in range(1, 23)}

# Sentimiento
NEGATIVE_WORDS = {
    "homicidio", "asesinato", "ataque", "ataques", "explosivo", "explosivos",
    "herido", "heridos", "muerto", "muertos", "secuestro", "extorsion",
    "robo", "hurto", "balacera", "sicariato", "terror", "inseguridad",
    "femicidio", "feminicidio", "masacre", "violacion", "abuso",
    "amenaza", "pandilla", "atraco", "tiroteo", "puñalada", "apuñalado",
}

POSITIVE_WORDS = {
    "captura", "capturas", "incautacion", "incauta", "prevencion",
    "comunidad", "control", "seguridad", "operativo", "rescate",
    "proteccion", "jornada", "programa", "bienestar", "convivencia",
}

# ── Categorías de clasificación (14 combinadas) ──────────────────────────
EVENT_RULES = {
    "Homicidio": [
        r"\bhomicid", r"\basesinad", r"\bmuert[oa]s?\b", r"\bfallecid",
        r"\bcadaver", r"\bultimad", r"\bmataron\b",
    ],
    "Sicariato": [
        r"\bsicari", r"\basesinad.*encargo", r"\bdisparo.*moto",
        r"\bhombre.*bala", r"\bmujer.*bala",
    ],
    "Hurto": [
        r"\bhurto", r"\brobo", r"\batraco", r"\bfleteo", r"\bescopolamina",
        r"\bhalad", r"\bcelular.*robad",
    ],
    "Hurto a vehiculos": [
        r"\bhurto.*vehicul", r"\bhurto.*carro", r"\bhurto.*moto",
        r"\brobo.*vehicul", r"\brobo.*carro", r"\brobo.*moto",
        r"\bautomovil.*hurtad", r"\bvehiculo.*robad",
    ],
    "Narcotrafico": [
        r"\bnarcotraf", r"\bmicrotraf", r"\bdroga", r"\bcocain",
        r"\bcargamento", r"\bincauta.*droga", r"\bkilo.*cocain",
        r"\bmarihuana", r"\bheroina", r"\bbase.*coca",
    ],
    "Reclutamiento forzado": [
        r"\breclutamiento", r"\breclutad", r"\bmenor.*armad",
        r"\bnino.*guerra", r"\bmenor.*reclut", r"\bexplotacion.*menor",
    ],
    "Explosivos/Terror": [
        r"\bexplosiv", r"\bbomba", r"\batentad", r"\bcarro bomba",
        r"\bhostigamiento", r"\bterror",
    ],
    "Secuestro/Extorsion": [
        r"\bsecuestro", r"\bextors", r"\bvacuna\b", r"\bplagi[oa]",
    ],
    "Crimen organizado": [
        r"\bdisidenc", r"\bclan\b", r"\bgrupo[s]? armad",
        r"\bmaf", r"\bbacrim", r"\bbanda criminal",
    ],
    "Accidentes y emergencias": [
        r"\baccident", r"\bemergenc", r"\bincendio", r"\bderrumbe",
        r"\bchoque", r"\binundacion",
    ],
    "Estafa/Fraude": [
        r"\bestafa", r"\bfraude", r"\bpiramide", r"\bestafador",
        r"\bengano",
    ],
    "Judicial/Control": [
        r"\bcaptur", r"\bimput", r"\bfiscal", r"\bpolicia",
        r"\boperativo", r"\bincauta",
    ],
    "Convivencia social": [
        r"\bri[aá]s?\b", r"\bintolerancia", r"\bvecin",
        r"\bconvivencia", r"\bpeleas?\b",
    ],
    "Prevencion/Comunidad": [
        r"\bprevenci", r"\bcampana", r"\bjornada", r"\bsecretaria",
        r"\bprograma", r"\besteriliza",
    ],
}

SEVERITY_MAP = {
    "Homicidio": 5, "Sicariato": 5, "Explosivos/Terror": 5,
    "Secuestro/Extorsion": 4, "Crimen organizado": 4,
    "Narcotrafico": 4, "Reclutamiento forzado": 4,
    "Hurto": 3, "Hurto a vehiculos": 3,
    "Accidentes y emergencias": 3, "Estafa/Fraude": 3,
    "Convivencia social": 2, "Judicial/Control": 2,
    "Prevencion/Comunidad": 1, "Sin clasificar": 1,
}

STOPWORDS_ES = {
    "de", "la", "el", "en", "y", "a", "los", "las", "del", "que", "por",
    "con", "para", "un", "una", "se", "al", "es", "su", "lo", "como",
    "mas", "pero", "sus", "le", "ya", "fue", "ha", "sin", "no", "son",
    "dos", "tambien", "esta", "este", "nos", "sobre", "ser", "entre",
    "tienen", "tiene", "muy", "sido", "hay", "desde", "estan", "todo",
    "hacia", "puede", "asi", "ante", "tras", "cada", "uno", "donde",
    "otro", "otra", "otros", "fue", "era", "han", "san", "dia", "hoy",
    "cali", "marzo", "2026", "2025", "segun", "asi", "ano", "anos",
    "dijo", "dijo", "van", "ver", "dan", "mas", "aqui", "alla",
}

CRITICAL_TERMS = [
    r"\bmuert", r"\bherid", r"\bexplosiv",
    r"\bsecuestro", r"\bextors", r"\batentad",
]

# ── Filtro geográfico ────────────────────────────────────────────────────
CALI_PATTERNS = [
    r"\bsantiago de cali\b", r"\bcali\b", r"\bvalle del cauca\b",
    r"\byumbo\b", r"\bjamundi\b", r"\bpalmira\b",
]

OTHER_CITY_PATTERNS = {
    "bogota": r"\bbogota\b", "medellin": r"\bmedellin\b",
    "barranquilla": r"\bbarranquilla\b", "cartagena": r"\bcartagena\b",
    "bucaramanga": r"\bbucaramanga\b", "cucuta": r"\bcucuta\b",
    "pasto": r"\bpasto\b", "pereira": r"\bpereira\b",
    "manizales": r"\bmanizales\b", "ibague": r"\bibague\b",
    "armenia": r"\barmenia\b", "neiva": r"\bneiva\b",
    "villavicencio": r"\bvillavicencio\b", "santa marta": r"\bsanta marta\b",
}


# ═══════════════════════════════════════════════════════════════════════════
# 2. FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════

def normalize_text(text: str) -> str:
    """Normaliza texto: minúsculas, sin acentos, sin caracteres especiales."""
    if pd.isna(text):
        return ""
    text = str(text).lower().strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def remove_emojis(value):
    """Elimina emojis de un valor de texto."""
    if isinstance(value, (list, np.ndarray)):
        return value
    try:
        if pd.isna(value):
            return value
    except (ValueError, TypeError):
        return value
    return EMOJI_RE.sub("", str(value)).strip()


def remove_ig_system_text(value):
    """Elimina el texto del sistema de Instagram (likes, comments, username, fecha)."""
    if isinstance(value, (list, np.ndarray)):
        return value
    try:
        if pd.isna(value):
            return value
    except (ValueError, TypeError):
        return value
    cleaned = IG_SYSTEM_RE.sub("", str(value))
    # Limpiar comillas finales sobrantes
    cleaned = re.sub(r'^["\']+|["\']+$', "", cleaned)
    return cleaned.strip()


def clean_text_format(value):
    """Mejora formato: normaliza espacios, saltos de línea y caracteres."""
    if isinstance(value, (list, np.ndarray)):
        return value
    try:
        if pd.isna(value):
            return value
    except (ValueError, TypeError):
        return value
    text = str(value)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([.,;:!?])", r"\1", text)
    return text.strip()


def detect_places(text: str) -> str | None:
    """Detecta barrios, comunas o corregimientos de Cali en el texto."""
    norm = normalize_text(text)
    found = []

    for token, label in BARRIOS_CALI.items():
        if token in norm:
            found.append(label)

    for token, label in CORREGIMIENTOS_CALI.items():
        if token in norm:
            found.append(label)

    for token, label in COMUNAS_CALI.items():
        if token in norm:
            found.append(label)

    # Dedup preservando orden
    seen = set()
    unique = []
    for place in found:
        if place not in seen:
            seen.add(place)
            unique.append(place)

    return ", ".join(unique) if unique else None


def score_sentiment(text: str) -> tuple[float, str]:
    """Puntaje de sentimiento basado en reglas."""
    norm = normalize_text(text)
    n_neg = sum(1 for w in NEGATIVE_WORDS if w in norm)
    n_pos = sum(1 for w in POSITIVE_WORDS if w in norm)
    den = max(1, n_neg + n_pos)
    score = (n_pos - n_neg) / den
    if score < -0.05:
        label = "Negativo"
    elif score > 0.05:
        label = "Positivo"
    else:
        label = "Neutro"
    return score, label


def classify_event(text: str) -> tuple[str, float]:
    """Clasifica un texto en categorías de hechos de seguridad."""
    norm = normalize_text(text)
    scores = {}
    for cat, patterns in EVENT_RULES.items():
        scores[cat] = sum(1 for p in patterns if re.search(p, norm))
    best = max(scores, key=scores.get)
    hits = scores[best]
    if hits <= 0:
        return "Sin clasificar", 0.0
    return best, min(0.95, 0.45 + 0.10 * hits)


def geo_filter(text: str) -> tuple[bool, bool]:
    """Retorna (menciona_cali, outside_cali)."""
    norm = normalize_text(text)
    in_cali = any(re.search(p, norm) for p in CALI_PATTERNS)
    other = any(re.search(p, norm) for p in OTHER_CITY_PATTERNS.values())
    outside = (not in_cali) and other
    return in_cali, outside


# ═══════════════════════════════════════════════════════════════════════════
# 3. CARGA DE DATOS
# ═══════════════════════════════════════════════════════════════════════════

def load_json(path: Path) -> list[dict]:
    """Carga un archivo JSON como lista de dicts."""
    if not path.exists():
        log.warning("Archivo no encontrado: %s", path)
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]


def load_dataframes() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Carga df_instagram y df_noticias desde los JSON."""

    # Instagram
    ig_data = load_json(PARSED_DIR / "instagram_cali.json")
    df_instagram = pd.DataFrame(ig_data) if ig_data else pd.DataFrame()
    log.info("Instagram: %d registros cargados", len(df_instagram))

    # Noticias (todos los demás JSON)
    news_files = [
        "blu_radio_cali.json",
        "el_pais_cali.json",
        "el_tiempo_nacional.json",
        "qhubo_cali.json",
    ]
    dfs = []
    for fn in news_files:
        data = load_json(PARSED_DIR / fn)
        if data:
            df_tmp = pd.DataFrame(data)
            df_tmp["source_file"] = Path(fn).stem
            dfs.append(df_tmp)
            log.info("  %s: %d registros", fn, len(df_tmp))

    df_noticias = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    log.info("Noticias: %d registros totales", len(df_noticias))

    return df_instagram, df_noticias


def filter_by_date(
    df: pd.DataFrame, days: int = 10, date_col: str = "fecha_publicacion"
) -> pd.DataFrame:
    """Filtra registros de los últimos *days* días."""
    if df.empty or date_col not in df.columns:
        return df
    cutoff = TODAY - timedelta(days=days)
    df["fecha_publicacion_dt"] = pd.to_datetime(
        df[date_col], dayfirst=True, errors="coerce"
    )
    before = len(df)
    df = df[df["fecha_publicacion_dt"] >= cutoff].copy()
    log.info(
        "  Filtro temporal (%d días): %d → %d registros",
        days, before, len(df),
    )
    return df


# ═══════════════════════════════════════════════════════════════════════════
# 4. LIMPIEZA DE DATOS
# ═══════════════════════════════════════════════════════════════════════════

def clean_dataframes(
    df_instagram: pd.DataFrame, df_noticias: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica limpieza de texto: sistema IG, emojis, formato, nulos."""

    text_cols = ["raw_text", "title", "snippet_text", "description_text"]

    # 1) Eliminar texto del sistema Instagram
    for col in text_cols:
        if col in df_instagram.columns:
            df_instagram[col] = df_instagram[col].apply(remove_ig_system_text)

    # También limpiar el texto dentro de comments_text
    if "comments_text" in df_instagram.columns:
        df_instagram["comments_text"] = df_instagram["comments_text"].apply(
            lambda lst: [remove_ig_system_text(t) for t in lst]
            if isinstance(lst, list)
            else lst
        )

    # 2) Eliminar emojis de ambos DFs
    for df in [df_instagram, df_noticias]:
        obj_cols = df.select_dtypes(include=["object"]).columns
        for col in obj_cols:
            df[col] = df[col].apply(remove_emojis)

    # También limpiar emojis dentro de comments_text y comments
    if "comments_text" in df_instagram.columns:
        df_instagram["comments_text"] = df_instagram["comments_text"].apply(
            lambda lst: [remove_emojis(t) for t in lst]
            if isinstance(lst, list)
            else lst
        )
    if "comments" in df_instagram.columns:
        def clean_comment_record(lst):
            if not isinstance(lst, list):
                return lst
            for c in lst:
                if isinstance(c, dict) and "texto" in c:
                    c["texto"] = remove_emojis(c["texto"])
            return lst
        df_instagram["comments"] = df_instagram["comments"].apply(clean_comment_record)

    # 3) Mejorar formato de texto
    for df in [df_instagram, df_noticias]:
        for col in text_cols:
            if col in df.columns:
                df[col] = df[col].apply(clean_text_format)

    # 4) Eliminar columnas 100% nulas
    for df_ref, name in [(df_instagram, "df_instagram"), (df_noticias, "df_noticias")]:
        null_cols = [c for c in df_ref.columns if df_ref[c].isna().all()]
        if null_cols:
            df_ref.drop(columns=null_cols, inplace=True)
            log.info("  %s: eliminadas %d columnas nulas: %s", name, len(null_cols), null_cols)

    # 5) Parsear fechas
    for df in [df_instagram, df_noticias]:
        if "fecha_publicacion" in df.columns:
            df["fecha_publicacion_dt"] = pd.to_datetime(
                df["fecha_publicacion"], dayfirst=True, errors="coerce"
            )
        if "fecha_obtencion" in df.columns:
            df["fecha_obtencion_dt"] = pd.to_datetime(
                df["fecha_obtencion"], dayfirst=True, errors="coerce"
            )

    log.info("Limpieza completada.")
    return df_instagram, df_noticias


# ═══════════════════════════════════════════════════════════════════════════
# 5. SEPARAR INSTAGRAM EN POSTS Y COMENTARIOS
# ═══════════════════════════════════════════════════════════════════════════

def split_instagram(
    df_instagram: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa df_instagram en df_instagram_noticias y df_instagram_comentarios."""

    if df_instagram.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Generar post_id
    if "canonical_id" in df_instagram.columns:
        df_instagram["post_id"] = df_instagram["canonical_id"].fillna(
            pd.Series(df_instagram.index.astype(str), index=df_instagram.index)
        )
    else:
        df_instagram["post_id"] = df_instagram.index.astype(str)

    # df_instagram_noticias  = todo menos comments crudos
    cols_drop = ["comments", "comments_text"]
    cols_keep = [c for c in df_instagram.columns if c not in cols_drop]
    df_ig_posts = df_instagram[cols_keep].copy()

    # df_instagram_comentarios = expandir comments
    rows = []
    for _, row in df_instagram.iterrows():
        post_id = row.get("post_id", "")
        comments = row.get("comments", [])
        if isinstance(comments, list):
            for com in comments:
                if isinstance(com, dict):
                    rows.append({
                        "post_id": post_id,
                        "usuario": com.get("usuario"),
                        "texto": com.get("texto", ""),
                        "fecha_hora": com.get("fecha_hora"),
                    })

    df_ig_comments = pd.DataFrame(rows)

    # Limpiar texto de comentarios
    if not df_ig_comments.empty and "texto" in df_ig_comments.columns:
        df_ig_comments["texto"] = df_ig_comments["texto"].apply(remove_emojis)
        df_ig_comments["texto"] = df_ig_comments["texto"].apply(clean_text_format)

    log.info(
        "Instagram separado: %d posts, %d comentarios",
        len(df_ig_posts),
        len(df_ig_comments),
    )
    return df_ig_posts, df_ig_comments


# ═══════════════════════════════════════════════════════════════════════════
# 6. DETECCIÓN DE LUGARES
# ═══════════════════════════════════════════════════════════════════════════

def add_lugar_hechos(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columna lugar_hechos detectando barrios/comunas/corregimientos."""
    if df.empty:
        return df

    content_cols = ["raw_text", "title", "snippet_text", "description_text"]
    available = [c for c in content_cols if c in df.columns]

    def _get_combined_text(row):
        parts = [str(row.get(c, "") or "") for c in available]
        return " ".join(parts)

    df["lugar_hechos"] = df.apply(lambda r: detect_places(_get_combined_text(r)), axis=1)
    n_detected = df["lugar_hechos"].notna().sum()
    log.info("  Lugares detectados en %d/%d registros", n_detected, len(df))
    return df


# ═══════════════════════════════════════════════════════════════════════════
# 7. ANÁLISIS NLP
# ═══════════════════════════════════════════════════════════════════════════

def run_nlp_analysis(
    df: pd.DataFrame, label: str = "datos"
) -> tuple[pd.DataFrame, dict]:
    """
    Ejecuta análisis de sentimiento y clasificación de hechos.
    Retorna (df_enriquecido, metricas).
    """
    if df.empty:
        return df, {}

    metrics = {"sentiment": {}, "event": {}, "prediction": {}}

    # --- Texto combinado ---
    content_cols = ["raw_text", "title", "snippet_text", "description_text"]
    available = [c for c in content_cols if c in df.columns]

    df["texto"] = df[available].fillna("").astype(str).agg(" ".join, axis=1)
    df["texto_norm"] = df["texto"].apply(normalize_text)

    # --- Filtro geográfico ---
    geo = df["texto"].apply(geo_filter)
    df["menciona_cali"] = geo.apply(lambda x: x[0])
    df["outside_cali"] = geo.apply(lambda x: x[1])

    df_work = df[~df["outside_cali"]].copy()
    n_excluded = len(df) - len(df_work)
    log.info("  [%s] Filtro geo: %d usados, %d excluidos", label, len(df_work), n_excluded)

    if df_work.empty:
        return df, metrics

    # --- Sentimiento base (reglas) ---
    sent = df_work["texto"].apply(score_sentiment)
    df_work["sentiment_score"] = sent.apply(lambda x: x[0]).astype(float)
    df_work["sentiment_label"] = sent.apply(lambda x: x[1])

    # Probabilidades proxy
    df_work["sent_neg"] = df_work["sentiment_score"].clip(upper=0).abs().clip(0, 1)
    df_work["sent_pos"] = df_work["sentiment_score"].clip(lower=0).clip(0, 1)
    df_work["sent_neu"] = (1 - (df_work["sent_neg"] + df_work["sent_pos"])).clip(0, 1)

    # --- Clasificación base (reglas) ---
    evt = df_work["texto_norm"].apply(classify_event).apply(pd.Series)
    evt.columns = ["hecho_categoria", "hecho_confianza"]
    df_work["hecho_categoria"] = evt["hecho_categoria"]
    df_work["hecho_confianza"] = evt["hecho_confianza"]

    # --- Fine-tune sentimiento (TF-IDF + LR) ---
    sent_train = df_work[
        df_work["sentiment_label"].isin(["Negativo", "Neutro", "Positivo"])
        & df_work["texto_norm"].ne("")
    ]
    sent_counts = sent_train["sentiment_label"].value_counts()

    if len(sent_counts) >= 2 and sent_counts.min() >= 8:
        log.info("  [%s] Fine-tuning sentimiento...", label)
        Xs = sent_train["texto_norm"]
        ys = sent_train["sentiment_label"]

        try:
            Xs_tr, Xs_val, ys_tr, ys_val = train_test_split(
                Xs, ys, test_size=0.2, random_state=42, stratify=ys
            )
        except Exception:
            Xs_tr, Xs_val, ys_tr, ys_val = Xs, Xs, ys, ys

        pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=40000, min_df=2)),
            ("clf", LogisticRegression(max_iter=2500, class_weight="balanced")),
        ])
        pipe.fit(Xs_tr, ys_tr)

        ys_tr_pred = pipe.predict(Xs_tr)
        ys_val_pred = pipe.predict(Xs_val)
        labels_order = sorted(ys.unique().tolist())

        metrics["sentiment"] = {
            "train_accuracy": float(accuracy_score(ys_tr, ys_tr_pred)),
            "val_accuracy": float(accuracy_score(ys_val, ys_val_pred)),
            "train_f1_macro": float(f1_score(ys_tr, ys_tr_pred, average="macro", zero_division=0)),
            "val_f1_macro": float(f1_score(ys_val, ys_val_pred, average="macro", zero_division=0)),
            "cm_train": confusion_matrix(ys_tr, ys_tr_pred, labels=labels_order).tolist(),
            "cm_val": confusion_matrix(ys_val, ys_val_pred, labels=labels_order).tolist(),
            "labels": labels_order,
            "report_val": classification_report(ys_val, ys_val_pred, output_dict=True, zero_division=0),
        }

        # Re-fit con todo para predicción
        pipe.fit(Xs, ys)
        df_work["sentiment_label_ft"] = pipe.predict(df_work["texto_norm"])

        proba = pipe.predict_proba(df_work["texto_norm"])
        classes = list(pipe.named_steps["clf"].classes_)
        idx_neg = classes.index("Negativo") if "Negativo" in classes else None
        idx_pos = classes.index("Positivo") if "Positivo" in classes else None
        if idx_neg is not None and idx_pos is not None:
            df_work["sentiment_score_ft"] = proba[:, idx_pos] - proba[:, idx_neg]
        else:
            df_work["sentiment_score_ft"] = 0.0
    else:
        df_work["sentiment_label_ft"] = df_work["sentiment_label"]
        df_work["sentiment_score_ft"] = df_work["sentiment_score"]

    # --- Fine-tune hechos (TF-IDF + LR) ---
    # Weak labels
    df_work[["hecho_cat_rule", "rule_hits"]] = (
        df_work["texto_norm"].apply(classify_event).apply(pd.Series)
    )

    evt_seed = df_work[
        (df_work["hecho_categoria"] != "Sin clasificar")
        & (df_work["hecho_confianza"] >= 0.55)
        & df_work["texto_norm"].ne("")
    ][["texto_norm", "hecho_categoria"]].copy()
    evt_seed["w"] = 1.0

    evt_weak = df_work[
        ((df_work["hecho_categoria"] == "Sin clasificar") | (df_work["hecho_confianza"] < 0.55))
        & (df_work["hecho_cat_rule"] != "Sin clasificar")
        & (df_work["rule_hits"] >= 1)
    ][["texto_norm", "hecho_cat_rule"]].copy()
    evt_weak = evt_weak.rename(columns={"hecho_cat_rule": "hecho_categoria"})
    evt_weak["w"] = 0.55

    evt_train = pd.concat([evt_seed, evt_weak], ignore_index=True)
    evt_counts = evt_train["hecho_categoria"].value_counts()

    if len(evt_counts) >= 3 and evt_counts.min() >= 3:
        log.info("  [%s] Fine-tuning clasificación de hechos...", label)
        Xe = evt_train["texto_norm"]
        ye = evt_train["hecho_categoria"]
        we = evt_train["w"].values

        try:
            Xe_tr, Xe_val, ye_tr, ye_val, we_tr, _ = train_test_split(
                Xe, ye, we, test_size=0.2, random_state=42, stratify=ye
            )
        except Exception:
            Xe_tr, Xe_val, ye_tr, ye_val, we_tr = Xe, Xe, ye, ye, we

        evt_pipe = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=50000, min_df=2)),
            ("clf", LogisticRegression(max_iter=3000, class_weight="balanced")),
        ])
        evt_pipe.fit(Xe_tr, ye_tr, clf__sample_weight=we_tr)

        ye_tr_pred = evt_pipe.predict(Xe_tr)
        ye_val_pred = evt_pipe.predict(Xe_val)
        evt_labels = sorted(ye.unique().tolist())

        metrics["event"] = {
            "train_accuracy": float(accuracy_score(ye_tr, ye_tr_pred)),
            "val_accuracy": float(accuracy_score(ye_val, ye_val_pred)),
            "train_f1_macro": float(f1_score(ye_tr, ye_tr_pred, average="macro", zero_division=0)),
            "val_f1_macro": float(f1_score(ye_val, ye_val_pred, average="macro", zero_division=0)),
            "cm_train": confusion_matrix(ye_tr, ye_tr_pred, labels=evt_labels).tolist(),
            "cm_val": confusion_matrix(ye_val, ye_val_pred, labels=evt_labels).tolist(),
            "labels": evt_labels,
            "report_val": classification_report(ye_val, ye_val_pred, output_dict=True, zero_division=0),
        }

        evt_pipe.fit(Xe, ye, clf__sample_weight=we)

        df_work["hecho_categoria_ft"] = evt_pipe.predict(df_work["texto_norm"])
        df_work["hecho_confianza_ft"] = evt_pipe.predict_proba(df_work["texto_norm"]).max(axis=1)

        # Fallback reglas para confianza baja
        low = df_work["hecho_confianza_ft"] < 0.45
        rule_ok = df_work["hecho_cat_rule"] != "Sin clasificar"
        df_work.loc[low & rule_ok, "hecho_categoria_ft"] = df_work.loc[low & rule_ok, "hecho_cat_rule"]
        df_work.loc[low & rule_ok, "hecho_confianza_ft"] = 0.50
    else:
        df_work["hecho_categoria_ft"] = df_work["hecho_categoria"]
        df_work["hecho_confianza_ft"] = df_work["hecho_confianza"]

    # --- Ensamble final ---
    df_work["sentiment_label_final"] = df_work["sentiment_label"]
    df_work["sentiment_score_final"] = df_work["sentiment_score"]
    mask_sent = (df_work["sentiment_label"] == "Neutro") | (df_work["sentiment_score"].abs() < 0.20)
    df_work.loc[mask_sent, "sentiment_label_final"] = df_work.loc[mask_sent, "sentiment_label_ft"]
    df_work.loc[mask_sent, "sentiment_score_final"] = df_work.loc[mask_sent, "sentiment_score_ft"]

    df_work["hecho_categoria_final"] = df_work["hecho_categoria"]
    df_work["hecho_confianza_final"] = df_work["hecho_confianza"]
    mask_evt = (df_work["hecho_categoria"] == "Sin clasificar") | (df_work["hecho_confianza"] < 0.65)
    df_work.loc[mask_evt, "hecho_categoria_final"] = df_work.loc[mask_evt, "hecho_categoria_ft"]
    df_work.loc[mask_evt, "hecho_confianza_final"] = df_work.loc[mask_evt, "hecho_confianza_ft"]

    # Rescue "Sin clasificar" con reglas
    still_unclass = (df_work["hecho_categoria_final"] == "Sin clasificar") & (df_work["hecho_cat_rule"] != "Sin clasificar")
    df_work.loc[still_unclass, "hecho_categoria_final"] = df_work.loc[still_unclass, "hecho_cat_rule"]
    df_work.loc[still_unclass, "hecho_confianza_final"] = 0.45

    # --- Severidad y riesgo ---
    df_work["severity"] = df_work["hecho_categoria_final"].map(SEVERITY_MAP).fillna(1).astype(int)
    df_work["critical_hits"] = df_work["texto_norm"].apply(
        lambda x: sum(1 for p in CRITICAL_TERMS if re.search(p, x))
    )
    df_work["risk_score"] = (
        (df_work["severity"] * 12)
        + ((-df_work["sentiment_score_final"]).clip(lower=0) * 30)
        + (df_work["critical_hits"] * 10)
    ).clip(0, 100).round(1)

    # --- Métricas de predicción ---
    sin_before = int((df_work["hecho_categoria"] == "Sin clasificar").sum())
    sin_after = int((df_work["hecho_categoria_final"] == "Sin clasificar").sum())
    total = len(df_work)
    metrics["prediction"] = {
        "n_total": total,
        "sin_clasificar_before": sin_before,
        "sin_clasificar_after": sin_after,
        "sin_before_pct": round(sin_before / max(1, total) * 100, 2),
        "sin_after_pct": round(sin_after / max(1, total) * 100, 2),
        "n_categorias_finales": int(df_work["hecho_categoria_final"].nunique()),
    }

    log.info(
        "  [%s] NLP completado: %d registros, Sin clasificar: %.1f%% → %.1f%%",
        label, total,
        metrics["prediction"]["sin_before_pct"],
        metrics["prediction"]["sin_after_pct"],
    )

    return df_work, metrics


# ═══════════════════════════════════════════════════════════════════════════
# 8. GENERACIÓN DE VISUALIZACIONES
# ═══════════════════════════════════════════════════════════════════════════

def generate_wordcloud(df: pd.DataFrame) -> BytesIO:
    """Genera nube de palabras y retorna imagen como BytesIO."""
    tokens = []
    for text in df["texto_norm"].fillna(""):
        tokens.extend(
            w for w in str(text).split()
            if len(w) > 3 and w not in STOPWORDS_ES and not w.isdigit()
        )

    freq = Counter(tokens)
    if not freq:
        freq = {"sin_datos": 1}

    wc = WordCloud(
        width=1000, height=500,
        background_color="white",
        colormap="RdYlGn_r",
        max_words=80,
        min_font_size=10,
    ).generate_from_frequencies(freq)

    buf = BytesIO()
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    ax.set_title("Nube de palabras — Términos más frecuentes", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_sentiment_chart(df: pd.DataFrame) -> BytesIO:
    """Gráfico de distribución de sentimiento."""
    col = "sentiment_label_final" if "sentiment_label_final" in df.columns else "sentiment_label"
    counts = df[col].value_counts()
    colors = {"Negativo": "#e74c3c", "Neutro": "#95a5a6", "Positivo": "#27ae60"}
    palette = [colors.get(l, "#3498db") for l in counts.index]

    buf = BytesIO()
    fig, ax = plt.subplots(figsize=(7, 4))
    counts.plot.bar(ax=ax, color=palette, edgecolor="white")
    ax.set_title("Distribución de sentimiento", fontsize=13, fontweight="bold")
    ax.set_ylabel("Cantidad de noticias")
    ax.set_xlabel("")
    for i, v in enumerate(counts.values):
        ax.text(i, v + 0.5, str(v), ha="center", fontweight="bold")
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_category_chart(df: pd.DataFrame) -> BytesIO:
    """Gráfico de distribución de categorías."""
    col = "hecho_categoria_final" if "hecho_categoria_final" in df.columns else "hecho_categoria"
    counts = df[col].value_counts().head(14)

    buf = BytesIO()
    fig, ax = plt.subplots(figsize=(8, 5))
    counts.plot.barh(ax=ax, color=sns.color_palette("viridis", len(counts)), edgecolor="white")
    ax.set_title("Clasificación de hechos de seguridad", fontsize=13, fontweight="bold")
    ax.set_xlabel("Cantidad de noticias")
    ax.invert_yaxis()
    for i, v in enumerate(counts.values):
        ax.text(v + 0.3, i, str(v), va="center", fontweight="bold", fontsize=9)
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_heatmap_lugar_categoria(df: pd.DataFrame) -> BytesIO:
    """Heatmap de lugar × categoría."""
    col_cat = "hecho_categoria_final" if "hecho_categoria_final" in df.columns else "hecho_categoria"
    df_filtered = df.dropna(subset=["lugar_hechos"])

    if df_filtered.empty:
        buf = BytesIO()
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "Sin datos de ubicación disponibles", ha="center", va="center", fontsize=14)
        ax.axis("off")
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return buf

    # Tomar solo el primer lugar si hay varios
    df_filtered = df_filtered.copy()
    df_filtered["lugar_principal"] = df_filtered["lugar_hechos"].str.split(",").str[0].str.strip()

    # Top 15 lugares
    top_places = df_filtered["lugar_principal"].value_counts().head(15).index.tolist()
    df_top = df_filtered[df_filtered["lugar_principal"].isin(top_places)]

    cross = pd.crosstab(df_top["lugar_principal"], df_top[col_cat])

    buf = BytesIO()
    fig, ax = plt.subplots(figsize=(12, 7))
    sns.heatmap(cross, annot=True, fmt="d", cmap="YlOrRd", ax=ax, linewidths=0.5)
    ax.set_title("Relación Lugar × Categoría de hecho", fontsize=13, fontweight="bold")
    ax.set_ylabel("Lugar")
    ax.set_xlabel("Categoría")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.yticks(fontsize=9)
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_daily_trend(df: pd.DataFrame) -> BytesIO:
    """Tendencia diaria de volumen y riesgo."""
    if "fecha_publicacion_dt" not in df.columns:
        buf = BytesIO()
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "Sin datos de fecha", ha="center", va="center")
        ax.axis("off")
        fig.savefig(buf, format="png", dpi=150)
        plt.close(fig)
        buf.seek(0)
        return buf

    daily = (
        df.dropna(subset=["fecha_publicacion_dt"])
        .groupby(df["fecha_publicacion_dt"].dt.date)
        .agg(noticias=("texto_norm", "count"), riesgo_medio=("risk_score", "mean"))
        .reset_index()
        .rename(columns={"fecha_publicacion_dt": "fecha"})
    )

    buf = BytesIO()
    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax1.bar(range(len(daily)), daily["noticias"], color="#3498db", alpha=0.7, label="Noticias")
    ax1.set_ylabel("Noticias", color="#3498db")
    ax1.set_xlabel("Fecha")
    ax1.set_xticks(range(len(daily)))
    ax1.set_xticklabels([str(d) for d in daily["fecha"]], rotation=45, ha="right", fontsize=7)

    if "riesgo_medio" in daily.columns:
        ax2 = ax1.twinx()
        ax2.plot(range(len(daily)), daily["riesgo_medio"], color="#e74c3c", marker="o",
                 linewidth=2, label="Riesgo medio")
        ax2.set_ylabel("Riesgo medio", color="#e74c3c")

    ax1.set_title("Tendencia diaria: Cobertura y Riesgo", fontsize=13, fontweight="bold")
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_confusion_matrix_img(cm: list, labels: list, title: str) -> BytesIO:
    """Genera imagen de matriz de confusión."""
    buf = BytesIO()
    cm_arr = np.array(cm)
    fig, ax = plt.subplots(figsize=(7, 5))
    sns.heatmap(cm_arr, annot=True, fmt="d", cmap="Blues", xticklabels=labels,
                yticklabels=labels, ax=ax, linewidths=0.5)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.set_ylabel("Real")
    ax.set_xlabel("Predicho")
    plt.xticks(rotation=45, ha="right", fontsize=8)
    plt.yticks(fontsize=8)
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def get_top_terms(df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """Top N términos más frecuentes."""
    tokens = []
    for text in df["texto_norm"].fillna(""):
        tokens.extend(
            w for w in str(text).split()
            if len(w) > 3 and w not in STOPWORDS_ES and not w.isdigit()
        )
    return pd.DataFrame(Counter(tokens).most_common(n), columns=["Término", "Frecuencia"])


# ═══════════════════════════════════════════════════════════════════════════
# 9. GENERACIÓN NARRATIVA CON OLLAMA
# ═══════════════════════════════════════════════════════════════════════════

def load_ollama_config() -> dict:
    """Carga configuración de Ollama."""
    cfg = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    return {
        "base_url": os.getenv("OLLAMA_BASE_URL", cfg.get("ollama_base_url", "http://localhost:11434")).rstrip("/"),
        "model": os.getenv("OLLAMA_MODEL", cfg.get("ollama_model", "llama3.1:8b")).strip(),
        "timeout": int(cfg.get("ollama_timeout_seconds", 60)),
    }


def generate_narrative_ollama(kpis: dict, top_places: list, top_categories: list,
                              top_terms_list: list, alerts: list) -> dict:
    """Genera texto narrativo usando Ollama para el reporte Word."""
    cfg = load_ollama_config()

    context = (
        f"CONTEXTO DEL ANÁLISIS:\n"
        f"- Total de noticias analizadas: {kpis.get('total', 0)}\n"
        f"- Periodo: {kpis.get('periodo', 'última semana')}\n"
        f"- Sentimiento negativo: {kpis.get('pct_neg', 0):.1f}%\n"
        f"- Sentimiento neutro: {kpis.get('pct_neu', 0):.1f}%\n"
        f"- Sentimiento positivo: {kpis.get('pct_pos', 0):.1f}%\n"
        f"- Noticias de alto riesgo (score>=70): {kpis.get('alto_riesgo', 0)} ({kpis.get('pct_alto_riesgo', 0):.1f}%)\n"
        f"- Principales categorías de hechos: {', '.join(top_categories[:5])}\n"
        f"- Principales barrios/lugares mencionados: {', '.join(top_places[:8])}\n"
        f"- Términos más frecuentes: {', '.join(top_terms_list[:10])}\n"
        f"- Alertas identificadas: {len(alerts)}\n"
    )

    prompt = (
        "Eres un analista de seguridad urbana experto en Santiago de Cali, Colombia. "
        "Redacta un informe profesional en español formal para el Secretario de Seguridad y Justicia "
        "de la Alcaldía de Santiago de Cali. El informe debe ayudar en la toma de decisiones sobre "
        "percepción de seguridad ciudadana.\n\n"
        f"{context}\n\n"
        "Responde SOLO con JSON válido con estas llaves:\n"
        "- resumen_ejecutivo: párrafo de 150-200 palabras con los hallazgos principales\n"
        "- lectura_semana: párrafo de 200-250 palabras con la lectura general de la semana\n"
        "- barrios_criticos: párrafo de 150-200 palabras sobre los barrios más problemáticos\n"
        "- recomendaciones: lista de 4-5 líneas de acción concretas para el Secretario\n"
        "- alertas_texto: párrafo de 100-150 palabras sobre las alertas principales\n"
        "- factores_riesgo: párrafo de 100-150 palabras sobre factores de riesgo identificados\n"
    )

    try:
        resp = requests.post(
            f"{cfg['base_url']}/api/generate",
            json={
                "model": cfg["model"],
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 2048},
            },
            timeout=cfg["timeout"],
        )
        resp.raise_for_status()
        body = resp.json()
        raw = body.get("response", "{}")
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, dict):
            log.info("Narrativa generada con Ollama exitosamente.")
            return data
    except Exception as e:
        log.warning("Ollama no disponible (%s). Usando plantillas de texto.", e)

    # Fallback: texto basado en datos
    return _fallback_narrative(kpis, top_places, top_categories, alerts)


def _fallback_narrative(kpis: dict, top_places: list, top_categories: list,
                        alerts: list) -> dict:
    """Genera texto narrativo de fallback cuando Ollama no está disponible."""
    total = kpis.get("total", 0)
    pct_neg = kpis.get("pct_neg", 0)
    pct_pos = kpis.get("pct_pos", 0)
    alto_riesgo = kpis.get("alto_riesgo", 0)
    pct_alto = kpis.get("pct_alto_riesgo", 0)

    places_str = ", ".join(top_places[:5]) if top_places else "diversos sectores de la ciudad"
    cats_str = ", ".join(top_categories[:4]) if top_categories else "diversas categorías"

    return {
        "resumen_ejecutivo": (
            f"El presente informe analiza {total} publicaciones provenientes de medios digitales "
            f"y redes sociales durante el periodo de monitoreo. El análisis de sentimiento revela "
            f"que el {pct_neg:.1f}% de la conversación digital tiene tono negativo, mientras que "
            f"el {pct_pos:.1f}% presenta un tono positivo. Se identificaron {alto_riesgo} noticias "
            f"de alto riesgo (score ≥ 70), representando el {pct_alto:.1f}% del total. "
            f"Los principales barrios mencionados son {places_str}. "
            f"Las categorías predominantes incluyen {cats_str}. "
            f"Este panorama sugiere la necesidad de implementar acciones focalizadas en los "
            f"sectores con mayor percepción de inseguridad."
        ),
        "lectura_semana": (
            f"Durante el periodo analizado, la conversación digital en Cali se concentró en "
            f"hechos relacionados con {cats_str}. Los sectores de {places_str} acumularon "
            f"la mayor cantidad de menciones en redes sociales y medios de comunicación. "
            f"El tono predominantemente negativo ({pct_neg:.1f}%) refleja una percepción "
            f"de inseguridad sostenida en la ciudadanía. Más allá de los hechos puntuales, "
            f"la reiteración de ciertos delitos en territorios específicos de la ciudad "
            f"genera una narrativa de vulnerabilidad que impacta la confianza ciudadana "
            f"en las instituciones de seguridad. Se observa una concentración temática en "
            f"delitos contra la vida y el patrimonio, con presencia significativa de "
            f"publicaciones sobre operativos de control por parte de las autoridades."
        ),
        "barrios_criticos": (
            f"Las publicaciones revisadas en redes sociales, medios de comunicación y plataformas "
            f"digitales hicieron referencia de manera reiterada a sectores como {places_str}. "
            f"Estos barrios concentran la mayor cantidad de menciones asociadas a hechos de "
            f"inseguridad y representan puntos críticos donde la percepción de riesgo es más alta. "
            f"Se recomienda priorizar acciones de prevención y control en estos territorios."
        ),
        "recomendaciones": [
            f"Priorizar acciones de prevención en los barrios con mayor mención en redes: {places_str}.",
            "Desarrollar encuentros de seguridad y convivencia con comerciantes y líderes comunitarios en los sectores priorizados.",
            "Realizar jornadas de recuperación y apropiación del espacio público en sectores con alta percepción de inseguridad.",
            "Fortalecer la presencia institucional y la oferta de servicios de seguridad en las comunas con mayor concentración de hechos.",
            "Implementar estrategias de comunicación para difundir resultados positivos de operativos y capturas.",
        ],
        "alertas_texto": (
            f"Se identificaron {len(alerts)} alertas de alto riesgo durante el periodo analizado. "
            f"Las principales corresponden a hechos de {cats_str} en los sectores de {places_str}. "
            f"Estas alertas requieren atención prioritaria por parte de las autoridades de seguridad."
        ),
        "factores_riesgo": (
            f"Los principales factores de riesgo identificados incluyen: concentración de hechos "
            f"delictivos en territorios específicos, percepción negativa sostenida en redes sociales "
            f"({pct_neg:.1f}% del contenido analizado), y presencia de noticias de alto riesgo "
            f"({pct_alto:.1f}%). La reiteración de ciertos delitos en los mismos barrios genera "
            f"un efecto amplificador en la percepción de inseguridad ciudadana."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 10. GENERACIÓN DEL DOCUMENTO WORD
# ═══════════════════════════════════════════════════════════════════════════

def _add_logos(doc: Document):
    """Agrega logos al encabezado del documento."""
    section = doc.sections[0]
    header = section.header
    header.is_linked_to_previous = False

    # Tabla de 1 fila × 3 columnas para logos + título
    tbl = header.add_table(rows=1, cols=3, width=Inches(7))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = True

    # Logo Observatorio (izquierda)
    cell_left = tbl.cell(0, 0)
    p_left = cell_left.paragraphs[0]
    p_left.alignment = WD_ALIGN_PARAGRAPH.LEFT
    if LOGO_OBSERVATORIO.exists():
        run = p_left.add_run()
        run.add_picture(str(LOGO_OBSERVATORIO), width=Cm(2.5))

    # Título centro
    cell_center = tbl.cell(0, 1)
    p_center = cell_center.paragraphs[0]
    p_center.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_c = p_center.add_run("Observatorio de Seguridad\nSantiago de Cali")
    run_c.font.size = Pt(8)
    run_c.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    # Logo Alcaldía (derecha)
    cell_right = tbl.cell(0, 2)
    p_right = cell_right.paragraphs[0]
    p_right.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    if LOGO_ALCALDIA.exists():
        run = p_right.add_run()
        run.add_picture(str(LOGO_ALCALDIA), width=Cm(2.0))

    # Eliminar bordes de la tabla
    from docx.oxml.ns import qn
    for cell in tbl.row_cells(0):
        tc = cell._element
        tcPr = tc.get_or_add_tcPr()
        borders = tcPr.find(qn("w:tcBorders"))
        if borders is not None:
            tc.remove(borders)


def _add_table_from_df(doc: Document, df: pd.DataFrame, max_rows: int = 30):
    """Agrega una tabla Word desde un DataFrame."""
    if df.empty:
        doc.add_paragraph("Sin datos disponibles.")
        return

    df_show = df.head(max_rows)
    table = doc.add_table(rows=1, cols=len(df_show.columns), style="Light Shading Accent 1")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Encabezados
    for i, col in enumerate(df_show.columns):
        cell = table.rows[0].cells[i]
        cell.text = str(col)
        for p in cell.paragraphs:
            for run in p.runs:
                run.font.size = Pt(8)
                run.font.bold = True

    # Filas
    for _, row in df_show.iterrows():
        row_cells = table.add_row().cells
        for i, val in enumerate(row):
            cell = row_cells[i]
            text = str(val) if pd.notna(val) else ""
            if len(text) > 100:
                text = text[:97] + "..."
            cell.text = text
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(7)


def _add_image(doc: Document, img_buf: BytesIO, width: float = 6.0):
    """Inserta imagen desde BytesIO."""
    img_buf.seek(0)
    doc.add_picture(img_buf, width=Inches(width))
    last_paragraph = doc.paragraphs[-1]
    last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def generate_word_report(
    df_analysis: pd.DataFrame,
    df_ig_posts: pd.DataFrame,
    df_ig_comments: pd.DataFrame,
    df_noticias: pd.DataFrame,
    metrics: dict,
    narrative: dict,
) -> Path:
    """Genera el documento Word profesional."""

    doc = Document()

    # ── Configurar estilos ──
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(11)

    # ── Logos en encabezado ──
    _add_logos(doc)

    # ── Pie de página ──
    section = doc.sections[0]
    footer = section.footer
    footer.is_linked_to_previous = False
    p_footer = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    p_footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_f = p_footer.add_run("Alcaldía de Santiago de Cali — Secretaría de Seguridad y Justicia — Documento Confidencial")
    run_f.font.size = Pt(7)
    run_f.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # ═══════════════════════════════════════════════════════════════════
    # PORTADA
    # ═══════════════════════════════════════════════════════════════════
    for _ in range(4):
        doc.add_paragraph("")

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_t = p_title.add_run("Monitoreo de redes sociales y medios digitales\nsobre seguridad en Cali")
    run_t.font.size = Pt(22)
    run_t.font.bold = True
    run_t.font.color.rgb = RGBColor(0x1A, 0x3A, 0x5C)

    doc.add_paragraph("")

    p_sub = doc.add_paragraph()
    p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_s = p_sub.add_run(f"Informe de Percepción de Seguridad\n{TODAY_DISPLAY}")
    run_s.font.size = Pt(14)
    run_s.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    doc.add_paragraph("")
    p_dest = doc.add_paragraph()
    p_dest.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_d = p_dest.add_run("Dirigido al Secretario de Seguridad y Justicia")
    run_d.font.size = Pt(12)
    run_d.font.italic = True
    run_d.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_page_break()

    # ═══════════════════════════════════════════════════════════════════
    # KPIs
    # ═══════════════════════════════════════════════════════════════════

    cat_col = "hecho_categoria_final" if "hecho_categoria_final" in df_analysis.columns else "hecho_categoria"
    sent_col = "sentiment_label_final" if "sentiment_label_final" in df_analysis.columns else "sentiment_label"

    total = len(df_analysis)
    negativos = int((df_analysis[sent_col] == "Negativo").sum()) if sent_col in df_analysis.columns else 0
    neutros = int((df_analysis[sent_col] == "Neutro").sum()) if sent_col in df_analysis.columns else 0
    positivos = int((df_analysis[sent_col] == "Positivo").sum()) if sent_col in df_analysis.columns else 0
    pct_neg = negativos / max(1, total) * 100
    pct_neu = neutros / max(1, total) * 100
    pct_pos = positivos / max(1, total) * 100
    alto_riesgo = int((df_analysis["risk_score"] >= 70).sum()) if "risk_score" in df_analysis.columns else 0
    pct_alto = alto_riesgo / max(1, total) * 100

    # Periodo
    if "fecha_publicacion_dt" in df_analysis.columns:
        dates = df_analysis["fecha_publicacion_dt"].dropna()
        if not dates.empty:
            periodo = f"{dates.min().strftime('%d/%m/%Y')} — {dates.max().strftime('%d/%m/%Y')}"
        else:
            periodo = TODAY_DISPLAY
    else:
        periodo = TODAY_DISPLAY

    # ── Sección 1: Introducción ──────────────────────────────────────
    doc.add_heading("1. Introducción", level=1)

    resumen = narrative.get("resumen_ejecutivo", "")
    doc.add_paragraph(resumen)

    # ── Sección 2: Datos básicos del análisis ────────────────────────
    doc.add_heading("2. Datos básicos del análisis", level=1)

    kpi_data = [
        ("Periodo de análisis", periodo),
        ("Total de publicaciones analizadas", str(total)),
        ("   — Instagram (posts)", str(len(df_ig_posts))),
        ("   — Instagram (comentarios)", str(len(df_ig_comments))),
        ("   — Medios digitales (noticias)", str(len(df_noticias))),
        ("Sentimiento negativo", f"{negativos} ({pct_neg:.1f}%)"),
        ("Sentimiento neutro", f"{neutros} ({pct_neu:.1f}%)"),
        ("Sentimiento positivo", f"{positivos} ({pct_pos:.1f}%)"),
        ("Noticias de alto riesgo (score ≥ 70)", f"{alto_riesgo} ({pct_alto:.1f}%)"),
        ("Categorías de hechos identificadas",
         str(df_analysis[cat_col].nunique()) if cat_col in df_analysis.columns else "N/A"),
    ]

    kpi_table = doc.add_table(rows=len(kpi_data), cols=2, style="Light Shading Accent 1")
    kpi_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (k, v) in enumerate(kpi_data):
        kpi_table.rows[i].cells[0].text = k
        kpi_table.rows[i].cells[1].text = v
        for cell in kpi_table.rows[i].cells:
            for p in cell.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(9)

    doc.add_paragraph("")

    # ── Sección 3: Lectura general ───────────────────────────────────
    doc.add_heading("3. Lectura general del periodo", level=1)
    doc.add_paragraph(narrative.get("lectura_semana", ""))

    # ── Tendencia diaria ──
    doc.add_heading("3.1 Tendencia diaria de cobertura y riesgo", level=2)
    trend_img = generate_daily_trend(df_analysis)
    _add_image(doc, trend_img, width=6.2)

    # ── Sección 4: Sentimiento ───────────────────────────────────────
    doc.add_heading("4. Análisis de sentimiento", level=1)

    doc.add_heading("4.1 Distribución de sentimiento", level=2)
    sent_img = generate_sentiment_chart(df_analysis)
    _add_image(doc, sent_img, width=5.5)

    # Estadísticas detalladas de emociones
    doc.add_heading("4.2 Estadísticas de emociones identificadas", level=2)
    if sent_col in df_analysis.columns:
        emotion_stats = df_analysis[sent_col].value_counts().reset_index()
        emotion_stats.columns = ["Sentimiento", "Cantidad"]
        emotion_stats["Porcentaje"] = (emotion_stats["Cantidad"] / max(1, total) * 100).round(1).astype(str) + "%"
        _add_table_from_df(doc, emotion_stats)

    doc.add_paragraph("")

    # ── Sección 5: Clasificación de hechos ───────────────────────────
    doc.add_heading("5. Clasificación de hechos de seguridad", level=1)

    doc.add_heading("5.1 Distribución por categoría", level=2)
    cat_img = generate_category_chart(df_analysis)
    _add_image(doc, cat_img, width=6.0)

    doc.add_heading("5.2 Detalle por categoría", level=2)
    if cat_col in df_analysis.columns:
        cat_detail = df_analysis[cat_col].value_counts().reset_index()
        cat_detail.columns = ["Categoría", "Cantidad"]
        cat_detail["Porcentaje"] = (cat_detail["Cantidad"] / max(1, total) * 100).round(1).astype(str) + "%"
        _add_table_from_df(doc, cat_detail)

    # ── Sección 6: Barrios críticos ──────────────────────────────────
    doc.add_heading("6. Principales barrios y sectores críticos", level=1)
    doc.add_paragraph(narrative.get("barrios_criticos", ""))

    # Tabla de barrios
    if "lugar_hechos" in df_analysis.columns:
        places_all = df_analysis["lugar_hechos"].dropna()
        if not places_all.empty:
            # Expandir lugares separados por coma
            all_places = []
            for p in places_all:
                all_places.extend([x.strip() for x in str(p).split(",") if x.strip()])
            places_freq = pd.DataFrame(
                Counter(all_places).most_common(15),
                columns=["Barrio/Sector", "Menciones"],
            )

            doc.add_heading("6.1 Barrios con mayor mención", level=2)
            _add_table_from_df(doc, places_freq)

    # Heatmap lugar × categoría
    doc.add_heading("6.2 Relación lugar × categoría de hecho", level=2)
    heatmap_img = generate_heatmap_lugar_categoria(df_analysis)
    _add_image(doc, heatmap_img, width=6.2)

    # ── Sección 7: Nube de palabras ──────────────────────────────────
    doc.add_heading("7. Nube de palabras y términos frecuentes", level=1)
    wc_img = generate_wordcloud(df_analysis)
    _add_image(doc, wc_img, width=5.8)

    doc.add_heading("7.1 Top 30 términos más frecuentes", level=2)
    top_terms_df = get_top_terms(df_analysis, 30)
    _add_table_from_df(doc, top_terms_df)

    # ── Sección 8: Alertas y factores de riesgo ──────────────────────
    doc.add_heading("8. Alertas y factores de riesgo", level=1)

    doc.add_heading("8.1 Alertas principales", level=2)
    doc.add_paragraph(narrative.get("alertas_texto", ""))

    # Top 10 noticias de mayor riesgo
    doc.add_heading("8.2 Top 10 noticias de mayor riesgo", level=2)
    if "risk_score" in df_analysis.columns:
        cols_top = [c for c in ["fecha_publicacion", "fuente", "title", cat_col, "risk_score"] if c in df_analysis.columns]
        top10 = df_analysis.sort_values("risk_score", ascending=False)[cols_top].head(10)
        _add_table_from_df(doc, top10, max_rows=10)

    doc.add_heading("8.3 Factores de riesgo", level=2)
    doc.add_paragraph(narrative.get("factores_riesgo", ""))

    # ── Sección 9: Métricas del modelo ───────────────────────────────
    doc.add_heading("9. Métricas del modelo de clasificación", level=1)

    # Sentimiento
    sent_m = metrics.get("sentiment", {})
    if sent_m and "train_accuracy" in sent_m:
        doc.add_heading("9.1 Modelo de sentimiento", level=2)
        m_data = [
            ("Accuracy (train)", f"{sent_m['train_accuracy']:.3f}"),
            ("Accuracy (validación)", f"{sent_m['val_accuracy']:.3f}"),
            ("F1-macro (train)", f"{sent_m['train_f1_macro']:.3f}"),
            ("F1-macro (validación)", f"{sent_m['val_f1_macro']:.3f}"),
        ]
        m_table = doc.add_table(rows=len(m_data), cols=2, style="Light Shading Accent 1")
        for i, (k, v) in enumerate(m_data):
            m_table.rows[i].cells[0].text = k
            m_table.rows[i].cells[1].text = v

        # Matriz de confusión
        if "cm_val" in sent_m and "labels" in sent_m:
            doc.add_heading("9.1.1 Matriz de confusión — Sentimiento (validación)", level=3)
            cm_img = generate_confusion_matrix_img(
                sent_m["cm_val"], sent_m["labels"],
                "Matriz de confusión — Sentimiento (validación)"
            )
            _add_image(doc, cm_img, width=5.0)

    # Hechos
    evt_m = metrics.get("event", {})
    if evt_m and "train_accuracy" in evt_m:
        doc.add_heading("9.2 Modelo de clasificación de hechos", level=2)
        m_data = [
            ("Accuracy (train)", f"{evt_m['train_accuracy']:.3f}"),
            ("Accuracy (validación)", f"{evt_m['val_accuracy']:.3f}"),
            ("F1-macro (train)", f"{evt_m['train_f1_macro']:.3f}"),
            ("F1-macro (validación)", f"{evt_m['val_f1_macro']:.3f}"),
        ]
        m_table = doc.add_table(rows=len(m_data), cols=2, style="Light Shading Accent 1")
        for i, (k, v) in enumerate(m_data):
            m_table.rows[i].cells[0].text = k
            m_table.rows[i].cells[1].text = v

        if "cm_val" in evt_m and "labels" in evt_m:
            doc.add_heading("9.2.1 Matriz de confusión — Hechos (validación)", level=3)
            cm_img = generate_confusion_matrix_img(
                evt_m["cm_val"], evt_m["labels"],
                "Matriz de confusión — Clasificación de hechos (validación)"
            )
            _add_image(doc, cm_img, width=5.5)

    # Predicción
    pred_m = metrics.get("prediction", {})
    if pred_m:
        doc.add_heading("9.3 Resumen de predicción", level=2)
        pred_data = [
            ("Total registros analizados", str(pred_m.get("n_total", 0))),
            ("Sin clasificar (antes)", f"{pred_m.get('sin_clasificar_before', 0)} ({pred_m.get('sin_before_pct', 0):.1f}%)"),
            ("Sin clasificar (después)", f"{pred_m.get('sin_clasificar_after', 0)} ({pred_m.get('sin_after_pct', 0):.1f}%)"),
            ("Categorías finales", str(pred_m.get("n_categorias_finales", 0))),
        ]
        p_table = doc.add_table(rows=len(pred_data), cols=2, style="Light Shading Accent 1")
        for i, (k, v) in enumerate(pred_data):
            p_table.rows[i].cells[0].text = k
            p_table.rows[i].cells[1].text = v

    # ── Sección 10: Líneas de acción ─────────────────────────────────
    doc.add_heading("10. Líneas de acción recomendadas", level=1)

    recs = narrative.get("recomendaciones", [])
    if isinstance(recs, list):
        for i, rec in enumerate(recs, 1):
            p = doc.add_paragraph()
            run_num = p.add_run(f"{i}. ")
            run_num.font.bold = True
            p.add_run(str(rec))
    elif isinstance(recs, str):
        doc.add_paragraph(recs)

    # ── Pie final ────────────────────────────────────────────────────
    doc.add_paragraph("")
    doc.add_paragraph("")
    p_end = doc.add_paragraph()
    p_end.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_end = p_end.add_run(
        "Documento generado automáticamente por el Observatorio de Seguridad de Santiago de Cali.\n"
        f"Fecha de generación: {TODAY_DISPLAY}"
    )
    run_end.font.size = Pt(8)
    run_end.font.italic = True
    run_end.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    # ── Guardar ──────────────────────────────────────────────────────
    out_path = REPORTS_DIR / f"reporte_percepcion_seguridad_cali_{TODAY_STR}.docx"
    doc.save(str(out_path))
    log.info("Reporte Word guardado: %s", out_path)
    return out_path


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    log.info("=" * 60)
    log.info("INICIO — Generador de Reporte de Seguridad")
    log.info("=" * 60)

    # ── 1) Carga ─────────────────────────────────────────────────────
    log.info("[1/8] Cargando datos...")
    df_instagram, df_noticias = load_dataframes()

    if df_instagram.empty and df_noticias.empty:
        log.error("No se encontraron datos. Verifica la carpeta %s", PARSED_DIR)
        sys.exit(1)

    # ── 1b) Filtro temporal ──────────────────────────────────────────
    log.info("Filtrando últimos %d días...", DATE_WINDOW_DAYS)
    df_instagram = filter_by_date(df_instagram, days=DATE_WINDOW_DAYS)
    df_noticias = filter_by_date(df_noticias, days=DATE_WINDOW_DAYS)

    if df_instagram.empty and df_noticias.empty:
        log.error("No hay datos en los últimos %d días.", DATE_WINDOW_DAYS)
        sys.exit(1)

    # ── 2) Limpieza ──────────────────────────────────────────────────
    log.info("[2/8] Limpiando textos (sistema IG, emojis, formato, nulos)...")
    df_instagram, df_noticias = clean_dataframes(df_instagram, df_noticias)

    # ── 3) Separar Instagram ─────────────────────────────────────────
    log.info("[3/8] Separando Instagram en posts y comentarios...")
    df_ig_posts, df_ig_comments = split_instagram(df_instagram)

    # ── 4) Detección de lugares ──────────────────────────────────────
    log.info("[4/8] Detectando lugares (barrios, comunas, corregimientos)...")
    df_ig_posts = add_lugar_hechos(df_ig_posts)
    df_noticias = add_lugar_hechos(df_noticias)

    # También en comentarios
    if not df_ig_comments.empty and "texto" in df_ig_comments.columns:
        df_ig_comments["lugar_hechos"] = df_ig_comments["texto"].apply(
            lambda t: detect_places(t) if pd.notna(t) else None
        )

    # ── 5) Combinar para análisis ────────────────────────────────────
    log.info("[5/8] Combinando datos para análisis NLP...")

    # Unificar columnas comunes
    common_cols = list(set(df_ig_posts.columns) & set(df_noticias.columns))
    df_all = pd.concat(
        [df_ig_posts[common_cols], df_noticias[common_cols]],
        ignore_index=True,
    )
    log.info("  Dataset combinado: %d registros", len(df_all))

    # ── 6) Análisis NLP ──────────────────────────────────────────────
    log.info("[6/8] Ejecutando análisis NLP (sentimiento + clasificación + riesgo)...")
    df_analysis, metrics = run_nlp_analysis(df_all, label="combinado")

    # ── 7) Generación narrativa ──────────────────────────────────────
    log.info("[7/8] Generando narrativa para el reporte...")

    cat_col = "hecho_categoria_final" if "hecho_categoria_final" in df_analysis.columns else "hecho_categoria"
    sent_col = "sentiment_label_final" if "sentiment_label_final" in df_analysis.columns else "sentiment_label"

    total = len(df_analysis)
    negativos = int((df_analysis[sent_col] == "Negativo").sum()) if sent_col in df_analysis.columns else 0
    neutros = int((df_analysis[sent_col] == "Neutro").sum()) if sent_col in df_analysis.columns else 0
    positivos = int((df_analysis[sent_col] == "Positivo").sum()) if sent_col in df_analysis.columns else 0
    alto_riesgo = int((df_analysis["risk_score"] >= 70).sum()) if "risk_score" in df_analysis.columns else 0

    # Top lugares
    top_places = []
    if "lugar_hechos" in df_analysis.columns:
        places_all = df_analysis["lugar_hechos"].dropna()
        all_p = []
        for p in places_all:
            all_p.extend([x.strip() for x in str(p).split(",") if x.strip()])
        top_places = [x[0] for x in Counter(all_p).most_common(10)]

    # Top categorías
    top_cats = df_analysis[cat_col].value_counts().head(6).index.tolist() if cat_col in df_analysis.columns else []

    # Top términos
    top_terms = get_top_terms(df_analysis, 15)
    top_terms_list = top_terms["Término"].tolist() if not top_terms.empty else []

    # Alertas (top riesgo)
    alerts = []
    if "risk_score" in df_analysis.columns:
        alerts = (
            df_analysis[df_analysis["risk_score"] >= 70]
            .sort_values("risk_score", ascending=False)
            .head(10)["title"]
            .tolist()
            if "title" in df_analysis.columns
            else []
        )

    # Periodo
    if "fecha_publicacion_dt" in df_analysis.columns:
        dates = df_analysis["fecha_publicacion_dt"].dropna()
        if not dates.empty:
            periodo = f"{dates.min().strftime('%d/%m/%Y')} — {dates.max().strftime('%d/%m/%Y')}"
        else:
            periodo = TODAY_DISPLAY
    else:
        periodo = TODAY_DISPLAY

    kpis = {
        "total": total,
        "periodo": periodo,
        "pct_neg": negativos / max(1, total) * 100,
        "pct_neu": neutros / max(1, total) * 100,
        "pct_pos": positivos / max(1, total) * 100,
        "alto_riesgo": alto_riesgo,
        "pct_alto_riesgo": alto_riesgo / max(1, total) * 100,
    }

    narrative = generate_narrative_ollama(kpis, top_places, top_cats, top_terms_list, alerts)

    # ── 8) Generar Word ──────────────────────────────────────────────
    log.info("[8/8] Generando documento Word...")
    out_path = generate_word_report(
        df_analysis=df_analysis,
        df_ig_posts=df_ig_posts,
        df_ig_comments=df_ig_comments,
        df_noticias=df_noticias,
        metrics=metrics,
        narrative=narrative,
    )

    log.info("=" * 60)
    log.info("REPORTE GENERADO EXITOSAMENTE: %s", out_path)
    log.info("=" * 60)

    # Resumen final
    print(f"\n{'='*60}")
    print(f"  REPORTE DE PERCEPCIÓN DE SEGURIDAD — SANTIAGO DE CALI")
    print(f"{'='*60}")
    print(f"  Archivo: {out_path}")
    print(f"  Total noticias analizadas: {total}")
    print(f"  Instagram posts: {len(df_ig_posts)}")
    print(f"  Instagram comentarios: {len(df_ig_comments)}")
    print(f"  Medios digitales: {len(df_noticias)}")
    print(f"  Sentimiento negativo: {kpis['pct_neg']:.1f}%")
    print(f"  Alto riesgo: {alto_riesgo} ({kpis['pct_alto_riesgo']:.1f}%)")
    pred = metrics.get("prediction", {})
    if pred:
        print(f"  Sin clasificar: {pred.get('sin_before_pct', 0):.1f}% → {pred.get('sin_after_pct', 0):.1f}%")
    print(f"{'='*60}\n")

    return out_path


if __name__ == "__main__":
    main()
