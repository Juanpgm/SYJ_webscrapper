from __future__ import annotations

import http.cookiejar
import itertools
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, urlparse

from selenium.common.exceptions import TimeoutException

from src.social.base_connector import BaseSocialConnector
from src.utils.dates import normalize_to_ddmmyyyy, now_ddmmyyyy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class _RateLimitDetected(Exception):
    """Raised when Instagram returns a rate-limit or block page."""


# ---------------------------------------------------------------------------
# Proxy rotation
# ---------------------------------------------------------------------------

class _ProxyRotator:
    """Round-robin proxy rotator with ban tracking."""

    def __init__(self, proxy_list: list[str]) -> None:
        self._proxies = list(proxy_list) if proxy_list else []
        self._cycle = itertools.cycle(self._proxies) if self._proxies else None
        self._current: str | None = None
        self._banned: set[str] = set()

    @property
    def has_proxies(self) -> bool:
        return bool(self._proxies)

    @property
    def current(self) -> str | None:
        return self._current

    def next(self) -> str | None:
        """Return the next available proxy, skipping banned ones."""
        if not self._cycle:
            return None
        for _ in range(len(self._proxies) + 1):
            p = next(self._cycle)
            if p not in self._banned:
                self._current = p
                log.info("Proxy rotado -> %s", _mask_proxy(p))
                return p
        log.warning("Todos los proxies estan baneados, usando conexion directa")
        self._current = None
        return None

    def ban_current(self) -> None:
        if self._current:
            log.warning("Proxy baneado: %s", _mask_proxy(self._current))
            self._banned.add(self._current)


def _mask_proxy(proxy: str) -> str:
    """Mask credentials in proxy URL for safe logging."""
    try:
        parsed = urlparse(proxy)
        if parsed.username:
            return f"{parsed.scheme}://***@{parsed.hostname}:{parsed.port}"
        return proxy
    except Exception:
        return "***"


def _extract_post_id(post_url: str) -> str | None:
    parsed = urlparse(post_url)
    parts = [part for part in parsed.path.split("/") if part]
    # Handle both /p/ID/ and /username/p/ID/ formats
    for i, segment in enumerate(parts):
        if segment in {"p", "reel", "tv"} and i + 1 < len(parts):
            return parts[i + 1]
    return None


def _is_blocked_page(driver) -> bool:
    """Check if Instagram is showing a login wall or rate-limit page."""
    try:
        src = driver.page_source[:5000].lower()
        blocked_signals = [
            "login to continue",
            "inicia sesión para continuar",
            "restrict",
            "challenge",
            "sorry, this page isn",
        ]
        return any(s in src for s in blocked_signals)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Selenium-based Instagram helpers
# ---------------------------------------------------------------------------

def _load_cookies_into_driver(driver, cookies_file: str | None) -> None:
    """Load Netscape cookie-jar file into the Selenium driver."""
    if not cookies_file or not Path(cookies_file).exists():
        return
    cj = http.cookiejar.MozillaCookieJar(cookies_file)
    cj.load(ignore_discard=True, ignore_expires=True)
    for c in cj:
        cookie_dict: dict = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "secure": c.secure,
        }
        if c.expires:
            cookie_dict["expiry"] = c.expires
        try:
            driver.add_cookie(cookie_dict)
        except Exception:
            pass


def _extract_post_links_from_profile(driver, profile_url: str, max_posts: int) -> list[str]:
    """Use Selenium to scroll a profile page and collect post URLs."""
    try:
        driver.get(profile_url)
    except TimeoutException:
        log.warning("Timeout cargando %s, intentando con HTML parcial", profile_url)
    time.sleep(2.0)

    if _is_blocked_page(driver):
        raise _RateLimitDetected(f"Pagina bloqueada al cargar {profile_url}")

    collected: list[str] = []
    last_count = 0
    stale_rounds = 0

    for _ in range(max(max_posts // 3, 4)):
        anchors = driver.find_elements("css selector", "a[href*='/p/'], a[href*='/reel/'], a[href*='/tv/']")
        for a in anchors:
            href = a.get_attribute("href") or ""
            if href and href not in collected:
                collected.append(href)
        if len(collected) >= max_posts:
            break
        if len(collected) == last_count:
            stale_rounds += 1
            if stale_rounds >= 3:
                break
        else:
            stale_rounds = 0
        last_count = len(collected)
        driver.execute_script("window.scrollBy(0, window.innerHeight);")
        time.sleep(0.8)

    return collected[:max_posts]


def _expand_comments(driver) -> None:
    """Click on 'View all comments' / 'Ver los X comentarios' to load full comment list."""
    expand_patterns = re.compile(
        r"(ver\s+(todos\s+)?los?\s+\d+\s+comentario|view\s+all\s+\d+\s+comment"
        r"|ver\s+m.s\s+comentario|view\s+more\s+comment)",
        re.IGNORECASE,
    )
    # Broad selectors: Instagram may use a, span, div, or button for this
    for sel in ["a", "span[role='link']", "div[role='button']", "button", "span"]:
        try:
            for el in driver.find_elements("css selector", sel):
                text = (el.text or "").strip()
                if text and len(text) < 80 and expand_patterns.search(text):
                    el.click()
                    time.sleep(1.5)
                    return
        except Exception:
            continue


_COMMENT_JUNK_PATTERNS = re.compile(
    r"^(\d+\s*[hmdws]|\d+\s*h(ora)?s?|\d+\s*d(ía)?s?|\d+\s*sem|\d+\s*min"
    r"|me gusta|likes?|responder|reply|publicidad|patrocinado|sponsored"
    r"|ver\s+\d+\s+respuesta|view\s+\d+\s+repl"
    r"|más|more|\.\.\.|…|ver\s+traducción|see\s+translation"
    r"|enviar|send|respuesta|contestar)$",
    re.IGNORECASE,
)


def _is_junk_text(text: str, caption: str, author: str | None) -> bool:
    """Return True if the text looks like a UI label, timestamp, or duplicate of caption/author."""
    t = text.strip()
    if not t or len(t) < 3:
        return True
    t_low = t.lower()
    cap_low = (caption or "").strip().lower()
    # Matches caption
    if cap_low and (t_low == cap_low or cap_low.startswith(t_low[:50]) or t_low.startswith(cap_low[:50])):
        return True
    # Is a username
    if author and t_low == author.lower():
        return True
    # Looks like pure username (single word, no spaces, starts with letter)
    if re.match(r"^[a-z_][a-z0-9_.]{1,30}$", t_low) and " " not in t:
        return True
    # Matches junk patterns
    if _COMMENT_JUNK_PATTERNS.match(t):
        return True
    # Pure emoji or very short
    stripped = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", t).strip()
    if len(stripped) < 2:
        return True
    return False


def _extract_comments_from_dom(driver, caption: str, max_comments: int) -> list[dict]:
    """Extract comments from the Instagram post DOM.

    Instagram 2026 renders each comment with a permalink <a> whose href
    matches ``/p/<post_id>/c/<comment_id>/``.  Going 3 levels up from
    that link reaches the comment container <div> which also holds
    a username profile link (``/<username>/``) and ``<span dir="auto">``
    elements with the comment text.
    """
    from selenium.webdriver.common.by import By  # local to avoid top-level import issues

    comments: list[dict] = []
    seen_texts: set[str] = set()

    _COMMENT_PERMALINK = re.compile(r"/p/[^/]+/c/\d+/")
    _USERNAME_HREF = re.compile(r"^/[a-zA-Z0-9_.]+/$")
    _USERNAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{1,29}$")

    try:
        permalink_links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
        for plink in permalink_links:
            if len(comments) >= max_comments:
                break
            href = (plink.get_attribute("href") or "")
            if not _COMMENT_PERMALINK.search(href):
                continue

            # Navigate up 3 levels to the comment container div
            try:
                container = plink.find_element(By.XPATH, "./../../..")
            except Exception:
                continue

            # Extract username from profile link inside the container
            usuario = None
            try:
                anchors = container.find_elements(By.CSS_SELECTOR, "a[href]")
                for a in anchors:
                    a_href = a.get_attribute("href") or ""
                    a_text = (a.text or "").strip()
                    if a_text and _USERNAME_PATTERN.match(a_text):
                        # Confirm the href is a profile link (/<username>/)
                        from urllib.parse import urlparse as _up
                        path = _up(a_href).path
                        if _USERNAME_HREF.match(path):
                            usuario = a_text
                            break
            except Exception:
                pass

            # Extract comment text from span[dir='auto']
            try:
                spans = container.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
                texto_parts: list[str] = []
                for span in spans:
                    t = (span.text or "").strip()
                    if t and not _is_junk_text(t, caption, usuario):
                        texto_parts.append(t)
                texto = " ".join(texto_parts).strip()
            except Exception:
                texto = ""

            if texto and len(texto) > 2 and texto not in seen_texts:
                seen_texts.add(texto)
                comments.append({
                    "usuario": usuario,
                    "texto": texto,
                    "fecha_hora": None,
                })

    except Exception:
        pass

    return comments[:max_comments]


def _scrape_post_page(driver, post_url: str, max_comments: int) -> dict | None:
    """Load a single post URL in Selenium and extract metadata from the page."""
    try:
        driver.get(post_url)
    except TimeoutException:
        log.warning("Timeout cargando post %s, intentando con HTML parcial", post_url)
    time.sleep(2.0)

    page_source = driver.page_source

    # --- Detect post type from URL ---
    is_reel = "/reel/" in post_url or "/reels/" in post_url
    is_tv = "/tv/" in post_url

    # --- Try JSON-LD first (Instagram sometimes embeds it) ---
    caption, author, published, is_video = "", None, None, is_reel or is_tv
    video_url: str | None = None
    try:
        ld_scripts = driver.find_elements("css selector", 'script[type="application/ld+json"]')
        for scr in ld_scripts:
            raw = scr.get_attribute("textContent") or ""
            if "instagram" not in raw.lower() and "ImageObject" not in raw and "VideoObject" not in raw:
                continue
            data = json.loads(raw)
            items = data if isinstance(data, list) else [data]
            for obj in items:
                caption = caption or str(obj.get("articleBody") or obj.get("caption") or obj.get("description") or "")
                author = author or str(obj.get("author", {}).get("name", "") if isinstance(obj.get("author"), dict) else obj.get("author") or "")
                date_str = obj.get("datePublished") or obj.get("uploadDate")
                if date_str and not published:
                    published = str(date_str)
                if obj.get("@type") == "VideoObject":
                    is_video = True
                    if not video_url:
                        video_url = obj.get("contentUrl") or obj.get("url") or None
    except Exception:
        pass

    # --- Fallback: parse meta tags ---
    if not caption:
        try:
            meta = driver.find_element("css selector", 'meta[property="og:description"]')
            caption = (meta.get_attribute("content") or "").strip()
        except Exception:
            pass
    if not caption:
        try:
            meta = driver.find_element("css selector", 'meta[name="description"]')
            caption = (meta.get_attribute("content") or "").strip()
        except Exception:
            pass

    # --- Detect video from page ---
    if not is_video:
        try:
            meta_type = driver.find_element("css selector", 'meta[property="og:type"]')
            if "video" in (meta_type.get_attribute("content") or "").lower():
                is_video = True
        except Exception:
            pass
    if not is_video and ("<video" in page_source[:50000]):
        is_video = True

    # --- Extract video URL from <video> tag or og:video meta ---
    if is_video and not video_url:
        try:
            meta_video = driver.find_element("css selector", 'meta[property="og:video"]')
            video_url = (meta_video.get_attribute("content") or "").strip() or None
        except Exception:
            pass
    if is_video and not video_url:
        try:
            meta_video = driver.find_element("css selector", 'meta[property="og:video:secure_url"]')
            video_url = (meta_video.get_attribute("content") or "").strip() or None
        except Exception:
            pass
    if is_video and not video_url:
        try:
            video_el = driver.find_element("css selector", "video source")
            video_url = (video_el.get_attribute("src") or "").strip() or None
        except Exception:
            pass
    if is_video and not video_url:
        try:
            video_el = driver.find_element("css selector", "video")
            video_url = (video_el.get_attribute("src") or "").strip() or None
        except Exception:
            pass

    # --- Filter out blob: URLs (not downloadable) ---
    if video_url and video_url.startswith("blob:"):
        video_url = None

    # --- Detect carousel (multiple images/videos) ---
    is_carousel = False
    try:
        carousel_indicators = driver.find_elements("css selector", "div[role='tablist'] > div, button[aria-label*='siguiente'], button[aria-label*='Next']")
        if carousel_indicators:
            is_carousel = True
    except Exception:
        pass

    # --- Try clicking "Ver más" / "more" to expand full caption ---
    # --- Try clicking "Ver más" / "more" to expand full caption ---
    try:
        for sel in ["div[role='button']", "button", "span[role='link']"]:
            clicked = False
            for btn in driver.find_elements("css selector", sel):
                btn_text = (btn.text or "").strip().lower()
                if btn_text in ("más", "mas", "more", "...más", "… más", "...more"):
                    btn.click()
                    time.sleep(0.5)
                    clicked = True
                    break
            if clicked:
                break
    except Exception:
        pass

    # --- Extract author from URL or page ---
    if not author:
        # Try extracting from the post URL itself (e.g. /username/p/ID/)
        try:
            url_parts = [p for p in urlparse(post_url).path.split("/") if p]
            if len(url_parts) >= 3 and url_parts[1] in {"p", "reel", "tv"}:
                author = url_parts[0]
        except Exception:
            pass
    if not author:
        # Try the first span[dir=auto] that looks like a username
        try:
            for span in driver.find_elements("css selector", "span[dir='auto']"):
                t = (span.text or "").strip()
                if t and re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]{1,29}$", t):
                    author = t
                    break
        except Exception:
            pass

    # --- Extract caption from visible DOM elements ---
    if not caption:
        try:
            for sel in [
                "h1",
                "h1 span",
                "span[dir='auto']",
            ]:
                elements = driver.find_elements("css selector", sel)
                for el in elements:
                    text = (el.text or "").strip()
                    if len(text) > 20 and not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]{1,29}$", text):
                        caption = text
                        break
                if caption:
                    break
        except Exception:
            pass

    # --- Published date from page ---
    if not published:
        try:
            time_el = driver.find_element("css selector", "time[datetime]")
            published = time_el.get_attribute("datetime")
        except Exception:
            pass

    # --- Comments from visible DOM ---
    comments: list[dict] = []
    try:
        # 1) Try clicking "View all X comments" / "Ver los X comentarios" to expand
        _expand_comments(driver)

        # 2) Extract comments with username from the comment list
        comments = _extract_comments_from_dom(driver, caption, max_comments)
    except Exception:
        pass

    # --- Determine post_type ---
    if is_reel:
        post_type = "reel"
    elif is_tv:
        post_type = "igtv"
    elif is_carousel:
        post_type = "carousel"
    elif is_video:
        post_type = "video_post"
    else:
        post_type = "image"

    post_id = _extract_post_id(post_url)
    return {
        "post_id": post_id,
        "webpage_url": post_url,
        "caption": caption,
        "author": author,
        "published": published,
        "is_video": is_video,
        "post_type": post_type,
        "video_url": video_url,
        "is_carousel": is_carousel,
        "comments": comments,
    }


class InstagramConnector(BaseSocialConnector):
    """Instagram connector using Selenium + cookies for profile listing,
    with yt-dlp fallback for video transcription only."""

    def fetch_items(
        self,
        *,
        start_date: datetime | None,
        end_date: datetime | None,
        keywords: list[str] | None,
        existing_urls: set[str] | None = None,
    ) -> list[dict]:
        profile_urls = list(self.source.get("profile_urls") or [])
        direct_post_urls = list(self.source.get("post_urls") or [])
        hashtags = list(self.source.get("hashtags") or [])
        max_posts = int(self.source.get("max_posts_per_profile", 6))
        max_comments = int(self.source.get("max_comments_per_post", 10))
        transcribe_videos = bool(self.source.get("transcribe_videos", True))
        cookies_file = self.source.get("cookies_file") or None
        cookies_browser = self.source.get("cookies_from_browser") or None
        filter_keywords = [k.lower() for k in (self.source.get("filter_keywords") or [])]
        if keywords:
            filter_keywords.extend(k.lower() for k in keywords)
        filter_keywords = list(dict.fromkeys(filter_keywords))

        known_urls: set[str] = set(existing_urls or ())

        whisper_model = str(self.source.get("whisper_model", "tiny"))
        whisper_device = str(self.source.get("whisper_device", "auto"))
        whisper_compute_type = str(self.source.get("whisper_compute_type", "int8"))

        listing_urls: list[str] = list(profile_urls)
        for hashtag in hashtags:
            clean = str(hashtag).strip().lstrip("#")
            if clean:
                listing_urls.append(f"https://www.instagram.com/explore/tags/{quote(clean)}/")

        # Build a Selenium driver for Instagram
        driver = self._build_ig_driver()
        if driver is None:
            log.error("Instagram: no se pudo crear driver Selenium; abortando")
            return []

        try:
            # Inject cookies
            try:
                driver.get("https://www.instagram.com/")
            except TimeoutException:
                log.warning("Timeout cargando instagram.com inicial")
            time.sleep(1.5)
            _load_cookies_into_driver(driver, cookies_file)
            driver.refresh()
            time.sleep(2.0)

            logged_in = "sessionid" in {c["name"] for c in driver.get_cookies()}
            log.info("Instagram Selenium: cookies cargadas, sesion=%s", "activa" if logged_in else "NO detectada")

            seen: set[str] = set()
            collected: list[dict] = []

            all_post_urls: list[str] = list(direct_post_urls)

            # --- Discover post URLs from profiles / hashtags ---
            for listing_url in listing_urls:
                log.info("Instagram: listando posts de %s", listing_url)
                try:
                    post_links = _extract_post_links_from_profile(driver, listing_url, max_posts)
                    log.info("Instagram: %d links encontrados en %s", len(post_links), listing_url)
                    all_post_urls.extend(post_links)
                except Exception as exc:
                    log.warning("Error listando Instagram %s: %s", listing_url, exc)

            # --- Process each post ---
            for post_url in all_post_urls:
                post_url = str(post_url).strip()
                if not post_url or post_url in seen or post_url in known_urls:
                    continue
                seen.add(post_url)

                try:
                    log.info("Instagram: scrapeando post %d/%d -> %s", len(seen), len(all_post_urls), post_url)
                    post_data = _scrape_post_page(driver, post_url, max_comments)
                    if not post_data:
                        log.info("Instagram: sin datos extraidos de %s", post_url)
                        continue

                    item = self._build_payload(
                        post_data,
                        transcribe_videos=transcribe_videos,
                        cookies_file=cookies_file,
                        cookies_browser=cookies_browser,
                        whisper_model=whisper_model,
                        whisper_device=whisper_device,
                        whisper_compute_type=whisper_compute_type,
                    )
                    if item and self._matches_keywords(item, filter_keywords):
                        # Date range filter
                        if not self._in_date_range(item, start_date, end_date):
                            log.info("Instagram: descartado (fuera de rango de fecha): %s", post_url)
                            continue
                        collected.append(item)
                        log.info("Instagram: +1 recolectado (total=%d): %s", len(collected), post_url)
                    elif item:
                        log.info("Instagram: descartado (sin keyword de seguridad): %s", post_url)
                except Exception as exc:
                    log.warning("Error scrapeando post %s: %s", post_url, exc)

            log.info("Instagram: %d posts recolectados de %d URLs procesadas",
                     len(collected), len(seen))
            return collected

        finally:
            try:
                driver.quit()
            except Exception:
                pass
            try:
                setattr(driver, "quit", lambda: None)
            except Exception:
                pass

    # ------------------------------------------------------------------

    @staticmethod
    def _build_ig_driver():
        """Create an undetected-chromedriver instance for Instagram."""
        try:
            import undetected_chromedriver as uc
        except ImportError:
            log.error("undetected-chromedriver no instalado")
            return None

        import os
        options = uc.ChromeOptions()
        browser_bin = (os.getenv("CHROME_BIN") or "").strip()
        if browser_bin:
            options.binary_location = browser_bin
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--window-size=1366,768")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=es-CO")
        options.add_argument("--mute-audio")
        # headless activado
        headless = True
        if headless:
            options.add_argument("--headless=new")

        driver_exe = (os.getenv("CHROMEDRIVER") or "").strip()
        try:
            if driver_exe:
                drv = uc.Chrome(options=options, driver_executable_path=driver_exe)
            else:
                drv = uc.Chrome(options=options)
            drv.set_page_load_timeout(20)
            drv.set_script_timeout(15)
            return drv
        except Exception as exc:
            log.error("No se pudo iniciar Chrome para Instagram: %s", exc)
            return None

    # ------------------------------------------------------------------

    @staticmethod
    def _matches_keywords(item: dict, filter_keywords: list[str]) -> bool:
        """Return True only if the post is about security AND is located in Cali."""
        searchable = " ".join([
            str(item.get("description_text") or ""),
            str(item.get("transcript_text") or ""),
            str(item.get("title") or ""),
            " ".join(item.get("comments_text") or []),
        ]).lower()

        # Geographic keywords — must mention Cali
        _GEO_CALI = [
            "cali", "santiago de cali", "valle del cauca",
            "distrito de cali", "suroccidente",
        ]
        # Barrios / zonas conocidas de Cali
        _BARRIOS_CALI = [
            "aguablanca", "siloé", "siloe", "alfonso lopez",
            "manuela beltran", "potrero grande", "terrón colorado",
            "terron colorado", "marroquín", "marroquin", "el vallado",
            "el retiro", "san antonio", "granada", "el peñón",
            "ciudad jardín", "ciudad jardin", "la flora", "menga",
            "chipichape", "sameco", "calima", "floralia",
            "el diamante", "los mangos", "el poblado", "mojica",
            "desepaz", "alfonso bonilla", "navarro", "comuna 13",
            "comuna 14", "comuna 15", "comuna 20", "comuna 21",
            "ladera", "oriente de cali",
        ]
        geo_ok = any(g in searchable for g in _GEO_CALI + _BARRIOS_CALI)

        # Security / crime keywords
        _SECURITY = [
            "seguridad", "inseguridad", "homicidio", "asesinato",
            "hurto", "robo", "atraco", "fleteo", "estafa", "fraude",
            "narcotrafico", "narcotráfico", "microtráfico", "microtrafico",
            "droga", "cocaina", "reclutamiento", "disidencia",
            "grupo armado", "guerrilla", "feminicidio",
            "violencia de género", "violencia de genero",
            "violencia intrafamiliar", "abuso sexual", "sicariato",
            "balacera", "tiroteo", "apuñalado", "puñalada",
            "extorsión", "extorsion", "secuestro", "desaparecido",
            "desaparecida", "pandilla", "delincuencia", "policía",
            "policia", "capturado", "captura", "operativo",
            "muerto", "víctima", "victima", "riña", "masacre",
            "banda criminal", "bacrim", "emergencia",
            "intolerancia", "intolerante",
        ]
        security_ok = any(s in searchable for s in _SECURITY)

        return geo_ok and security_ok

    # ------------------------------------------------------------------

    @staticmethod
    def _in_date_range(item: dict, start_date: datetime | None, end_date: datetime | None) -> bool:
        """Return True if item's fecha_publicacion is within [start_date, end_date]."""
        if not start_date and not end_date:
            return True
        date_str = item.get("fecha_publicacion", "")
        if not date_str:
            return True
        try:
            dt = datetime.strptime(date_str, "%d/%m/%Y")
        except (ValueError, TypeError):
            return True
        if start_date and dt < start_date:
            return False
        if end_date and dt > end_date:
            return False
        return True

    # ------------------------------------------------------------------

    @staticmethod
    def _apply_cookie_opts(opts: dict, cookies_file: str | None, cookies_browser: str | None) -> None:
        if cookies_file:
            opts["cookiefile"] = cookies_file
        elif cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)

    # ------------------------------------------------------------------

    def _build_payload(
        self,
        post_data: dict,
        *,
        transcribe_videos: bool,
        cookies_file: str | None,
        cookies_browser: str | None,
        whisper_model: str,
        whisper_device: str,
        whisper_compute_type: str,
    ) -> dict | None:
        """Convert Selenium-scraped post_data into the standard output payload."""
        post_id = post_data.get("post_id")
        webpage_url = post_data.get("webpage_url", "")
        caption = post_data.get("caption") or ""
        author = post_data.get("author")
        published = post_data.get("published")
        is_video = post_data.get("is_video", False)
        post_type = post_data.get("post_type", "image")
        video_url = post_data.get("video_url")
        is_carousel = post_data.get("is_carousel", False)
        comments = post_data.get("comments") or []
        comments_text = [c["texto"] for c in comments if c.get("texto")]

        # Video transcription deshabilitada temporalmente
        transcript_text = ""
        transcript_source = None

        if not any([caption, comments_text]):
            return None

        content_kind = post_type

        title = (caption or transcript_text or (comments_text[0] if comments_text else "Instagram post")).strip()

        sections: list[str] = []
        if caption:
            sections.append(f"Descripcion: {caption}")
        if transcript_text:
            sections.append(f"Transcripcion ({transcript_source}): {transcript_text}")
        if comments_text:
            sections.append("Comentarios: " + " || ".join(comments_text))

        raw_text = "\n\n".join(sections).strip() or title
        if not raw_text:
            return None

        return {
            "fecha_obtencion": now_ddmmyyyy(),
            "fecha_publicacion": normalize_to_ddmmyyyy(published),
            "fuente": self.source.get("name", "Instagram Publico"),
            "raw_text": raw_text,
            "snippet_text": (transcript_text[:280] if transcript_text else caption[:280] if caption else title[:280]),
            "title": title,
            "url_noticia": webpage_url,
            "source_type": "social",
            "platform": "instagram",
            "content_kind": content_kind,
            "author_name": author,
            "canonical_id": post_id,
            "description_text": caption or None,
            "transcript_text": transcript_text or None,
            "transcript_source": transcript_source,
            "comments_text": comments_text,
            "comments": comments,
            "n_comments": len(comments),
            "video_url": video_url,
            "reel_url": webpage_url if post_type == "reel" else None,
            "is_carousel": is_carousel,
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _transcribe_video(
        post_url: str,
        cookies_file: str | None,
        cookies_browser: str | None,
        whisper_model: str,
        whisper_device: str,
        whisper_compute_type: str,
        timeout: int = 30,
    ) -> str:
        """Download audio via yt-dlp and transcribe with Whisper."""
        try:
            import concurrent.futures
            from yt_dlp import YoutubeDL

            with TemporaryDirectory() as tmpdir:
                outtmpl = str(Path(tmpdir) / "%(id)s.%(ext)s")
                dl_opts: dict = {
                    "format": "bestaudio/best",
                    "quiet": True,
                    "no_warnings": True,
                    "noprogress": True,
                    "noplaylist": True,
                    "outtmpl": outtmpl,
                    "retries": 1,
                    "fragment_retries": 1,
                    "socket_timeout": 15,
                    "cachedir": False,
                }
                InstagramConnector._apply_cookie_opts(dl_opts, cookies_file, cookies_browser)

                def _download():
                    with YoutubeDL(dl_opts) as ydl:
                        return ydl.extract_info(post_url, download=True)

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_download)
                    try:
                        info = future.result(timeout=timeout)
                    except concurrent.futures.TimeoutError:
                        log.warning("Timeout descargando audio de %s (%ds)", post_url, timeout)
                        return ""

                audio_path = None
                requested = (info or {}).get("requested_downloads") or []
                if requested:
                    candidate = requested[0].get("filepath") or requested[0].get("filename")
                    if candidate and Path(candidate).exists():
                        audio_path = Path(candidate)
                if audio_path is None:
                    for fp in Path(tmpdir).glob("*"):
                        if fp.is_file() and fp.stat().st_size > 0:
                            audio_path = fp
                            break
                if audio_path is None:
                    return ""

                from faster_whisper import WhisperModel

                model = WhisperModel(whisper_model, device=whisper_device, compute_type=whisper_compute_type)
                segments, _ = model.transcribe(
                    str(audio_path), language="es", vad_filter=True, beam_size=1,
                )
                return " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as exc:
            log.debug("Fallo transcripcion video Instagram %s: %s", post_url, exc)
            return ""