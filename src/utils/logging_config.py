import logging
from pathlib import Path


def configure_logging() -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler("logs/scraper.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
