from abc import ABC, abstractmethod


class BaseScraper(ABC):
    @abstractmethod
    def fetch_html(self, url: str) -> str:
        raise NotImplementedError
