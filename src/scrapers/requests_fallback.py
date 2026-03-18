from __future__ import annotations

import random

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.scrapers.base_scraper import BaseScraper
from src.utils.retry import retry_policy


class RequestsScraper(BaseScraper):
    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    ]

    def __init__(self, timeout_seconds: int = 25) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        # Avoid accidental VS Code/local proxy leakage that breaks outbound calls.
        self.session.trust_env = False

        retry = Retry(
            total=4,
            backoff_factor=0.4,
            status_forcelist=[403, 408, 409, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524],
            allowed_methods=frozenset(["GET", "HEAD"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(pool_connections=128, pool_maxsize=128, max_retries=retry)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _build_headers(self, url: str) -> dict[str, str]:
        host = requests.utils.urlparse(url).netloc
        return {
            "User-Agent": random.choice(self._USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-CO,es;q=0.9,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Referer": f"https://{host}/",
        }

    @retry_policy(max_attempts=5)
    def fetch_html(self, url: str) -> str:
        response = self.session.get(
            url,
            timeout=self.timeout_seconds,
            headers=self._build_headers(url),
            allow_redirects=True,
        )
        response.raise_for_status()
        if not response.text or len(response.text) < 200:
            raise RuntimeError("Respuesta HTML vacia o demasiado corta")
        return response.text
