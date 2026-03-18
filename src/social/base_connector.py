from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Callable


class BaseSocialConnector(ABC):
    def __init__(
        self,
        source: dict,
        fetch_html: Callable[[str], str],
        browser_fetch_html: Callable[[str], str] | None = None,
    ) -> None:
        self.source = source
        self.fetch_html = fetch_html
        self.browser_fetch_html = browser_fetch_html

    @abstractmethod
    def fetch_items(
        self,
        *,
        start_date: datetime | None,
        end_date: datetime | None,
        keywords: list[str] | None,
    ) -> list[dict]:
        raise NotImplementedError
