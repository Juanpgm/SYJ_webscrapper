from __future__ import annotations

import os
import random
import time
from threading import Lock

from src.scrapers.base_scraper import BaseScraper
from src.utils.retry import retry_policy


class SeleniumScraper(BaseScraper):
    """Browser scraper for dynamic pages with anti-bot mitigations."""

    def __init__(self, timeout_seconds: int = 30, headless: bool = True) -> None:
        self.timeout_seconds = timeout_seconds
        self.headless = headless
        self._driver = None
        self._lock = Lock()

        try:
            import undetected_chromedriver as uc  # type: ignore

            self._uc = uc
        except Exception as exc:
            raise RuntimeError(
                "undetected-chromedriver no esta instalado. Ejecuta: pip install undetected-chromedriver selenium"
            ) from exc

        try:
            from selenium.webdriver.support.ui import WebDriverWait  # type: ignore

            self._WebDriverWait = WebDriverWait
        except Exception as exc:
            raise RuntimeError("selenium no esta instalado. Ejecuta: pip install selenium") from exc

    def _sleep_like_human(self, minimum: float = 0.9, maximum: float = 2.6) -> None:
        value = random.gauss(1.4, 0.45)
        time.sleep(max(minimum, min(maximum, value)))

    @staticmethod
    def _looks_like_verification_page(html: str) -> bool:
        marker = html.lower()
        return any(
            token in marker
            for token in (
                "verifying your browser",
                "verifying your request",
                "checking your browser",
                "cf-challenge",
                "captcha",
            )
        )

    def _build_driver(self):
        options = self._uc.ChromeOptions()
        browser_executable = str(os.getenv("CHROME_BIN") or "").strip()
        driver_executable = str(os.getenv("CHROMEDRIVER") or "").strip()

        if browser_executable:
            options.binary_location = browser_executable
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1366,768")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=es-CO")
        if self.headless:
            options.add_argument("--headless=new")

        if driver_executable:
            return self._uc.Chrome(options=options, driver_executable_path=driver_executable)
        return self._uc.Chrome(options=options)

    def _driver_instance(self):
        if self._driver is not None:
            return self._driver

        with self._lock:
            if self._driver is None:
                self._driver = self._build_driver()
        return self._driver

    @retry_policy(max_attempts=3)
    def fetch_html(self, url: str) -> str:
        driver = self._driver_instance()
        driver.set_page_load_timeout(self.timeout_seconds)
        driver.get(url)

        wait = self._WebDriverWait(driver, self.timeout_seconds)
        wait.until(lambda d: d.execute_script("return document.readyState") == "complete")

        # Scroll to trigger lazy-loaded sections in article pages.
        self._sleep_like_human()
        driver.execute_script("window.scrollTo(0, Math.floor(document.body.scrollHeight * 0.35));")
        self._sleep_like_human()
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        self._sleep_like_human()
        driver.execute_script("window.scrollTo(0, 0);")

        html = driver.page_source
        if self._looks_like_verification_page(html):
            for attempt in range(2):
                time.sleep(4 + attempt)
                try:
                    driver.refresh()
                    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
                except Exception:
                    pass
                self._sleep_like_human(1.0, 2.0)
                html = driver.page_source
                if html and len(html) >= 300 and not self._looks_like_verification_page(html):
                    break
        if not html or len(html) < 300:
            raise RuntimeError("Respuesta HTML vacia o demasiado corta en Selenium")
        return html

    def close(self) -> None:
        if self._driver is None:
            return

        with self._lock:
            if self._driver is not None:
                driver = self._driver
                try:
                    driver.quit()
                finally:
                    # undetected-chromedriver calls quit again in __del__.
                    # Replacing the bound method avoids noisy WinError logs.
                    try:
                        setattr(driver, "quit", lambda: None)
                    except Exception:
                        pass
                self._driver = None
