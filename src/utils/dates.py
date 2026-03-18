from datetime import datetime
from dateutil import parser
import re


def now_ddmmyyyy() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def normalize_to_ddmmyyyy(value: str | None) -> str:
    if not value:
        return now_ddmmyyyy()

    try:
        cleaned = value.strip()

        # ISO-like timestamps already encode year-month-day order explicitly.
        if re.match(r"^\d{4}[-/]\d{2}[-/]\d{2}(?:[T\s].*)?$", cleaned):
            normalized = cleaned.replace("Z", "+00:00")
            dt = parser.isoparse(normalized.replace("/", "-"))
        else:
            dt = parser.parse(cleaned, dayfirst=True, fuzzy=True)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return now_ddmmyyyy()
