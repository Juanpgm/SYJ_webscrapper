"""
enrich_comments.py — Pipeline secundario para extraer comentarios de Instagram.

Lee los posts ya scrapeados de data/parsed_json/instagram_cali.json,
abre cada URL en Selenium, extrae los comentarios y los imputa de vuelta
al JSON sin necesidad de re-correr el scraper completo.

Uso:
    python enrich_comments.py                       # enriquece todos los posts sin comentarios
    python enrich_comments.py --all                 # re-extrae para TODOS los posts
    python enrich_comments.py --max 10              # procesa max 10 posts
    python enrich_comments.py --file data/parsed_json/instagram_cali.json
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

DEFAULT_JSON = Path("data/parsed_json/instagram_cali.json")
DEFAULT_COOKIES = Path("config/instagram_cookies.txt")
MAX_COMMENTS = 500

_REPORTED_COMMENTS_RE = re.compile(r"(\d+)\s+comments?")


def _reported_comment_count(post: dict) -> int:
    """Extract the reported comment count from IG metadata text (e.g. '72 comments')."""
    text = post.get("description_text") or post.get("snippet_text") or post.get("raw_text") or ""
    m = _REPORTED_COMMENTS_RE.search(text)
    return int(m.group(1)) if m else -1  # -1 = unknown

# ---------------------------------------------------------------------------
# Junk-text filter (mirrors instagram_connector.py)
# ---------------------------------------------------------------------------
_COMMENT_JUNK_PATTERNS = re.compile(
    r"^(\d+\s*[hmdws]|\d+\s*h(ora)?s?|\d+\s*d(ía)?s?|\d+\s*sem|\d+\s*min"
    r"|me gusta|likes?|responder|reply|publicidad|patrocinado|sponsored"
    r"|ver\s+\d+\s+respuesta|view\s+\d+\s+repl"
    r"|más|more|\.\.\.|…|ver\s+traducción|see\s+translation"
    r"|enviar|send|respuesta|contestar)$",
    re.IGNORECASE,
)


def _is_junk_text(text: str, caption: str, author: str | None) -> bool:
    t = text.strip()
    if not t or len(t) < 3:
        return True
    t_low = t.lower()
    cap_low = (caption or "").strip().lower()
    if cap_low and (t_low == cap_low or cap_low.startswith(t_low[:50]) or t_low.startswith(cap_low[:50])):
        return True
    if author and t_low == author.lower():
        return True
    if re.match(r"^[a-z_][a-z0-9_.]{1,30}$", t_low) and " " not in t:
        return True
    if _COMMENT_JUNK_PATTERNS.match(t):
        return True
    stripped = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\ufe00-\ufe0f]", "", t).strip()
    if len(stripped) < 2:
        return True
    return False


# ---------------------------------------------------------------------------
# Selenium driver setup
# ---------------------------------------------------------------------------

def _create_driver():
    """Create an undetected-chromedriver instance (headless=False for IG)."""
    try:
        import undetected_chromedriver as uc
    except ImportError:
        log.error("undetected-chromedriver no instalado: pip install undetected-chromedriver")
        sys.exit(1)

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
    options.add_argument("--headless=new")

    driver_exe = (os.getenv("CHROMEDRIVER") or "").strip()
    try:
        drv = uc.Chrome(options=options, driver_executable_path=driver_exe) if driver_exe else uc.Chrome(options=options)
        drv.set_page_load_timeout(20)
        drv.set_script_timeout(15)
        return drv
    except Exception as exc:
        log.error("No se pudo iniciar Chrome: %s", exc)
        sys.exit(1)


def _load_cookies(driver, cookies_file: Path) -> None:
    if not cookies_file.exists():
        log.warning("Archivo de cookies no encontrado: %s", cookies_file)
        return
    driver.get("https://www.instagram.com/")
    time.sleep(2)
    cj = http.cookiejar.MozillaCookieJar(str(cookies_file))
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
    driver.refresh()
    time.sleep(2)
    # Verify session
    src = driver.page_source.lower()
    if "login" in src[:5000] and "ds_user_id" not in str(driver.get_cookies()):
        log.warning("Sesion de Instagram NO activa — los comentarios pueden no cargar")
    else:
        log.info("Sesion Instagram activa")


# ---------------------------------------------------------------------------
# Comment expansion + extraction
# ---------------------------------------------------------------------------

def _expand_comments(driver, max_rounds: int = 80) -> None:
    """Expand ALL comments and reply threads on the post.

    Primary strategy: SCROLL the comment panel container to trigger
    Instagram's infinite-scroll lazy loading.  Reel pages have NO
    "Ver más comentarios" button — comments load only via scroll.

    Secondary: click reply-expand buttons and hidden-comment reveals.
    Ground truth = count of permalink elements (a[role='link'] with /c/\\d+/).
    """
    from selenium.webdriver.common.by import By

    _MAIN_EXPAND = re.compile(
        r"(ver\s+(todos?\s+)?los?\s+\d+\s+comentario|view\s+all\s+\d+\s+comment"
        r"|ver\s+m.s\s+comentario|view\s+more\s+comment"
        r"|cargar\s+m.s\s+comentario|load\s+more\s+comment"
        r"|ver\s+comentarios?\s+anterior|view\s+previous\s+comment"
        r"|\+)",
        re.IGNORECASE,
    )
    _REPLY_EXPAND = re.compile(
        r"(ver\s+(las?\s+)?\d*\s*respuesta|view\s+(\d+\s+)?repl"
        r"|ver\s+respuesta)",
        re.IGNORECASE,
    )
    _HIDE = re.compile(r"(ocultar|hide)", re.IGNORECASE)
    _PERMALINK = re.compile(r"/p/[^/]+/c/\d+/|/reel/[^/]+/c/\d+/")

    SELECTORS = ["div[role='button']", "span[role='link']", "button", "a", "span"]

    def _count_permalinks() -> int:
        try:
            return sum(
                1 for el in driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
                if _PERMALINK.search(el.get_attribute("href") or "")
            )
        except Exception:
            return 0

    def _find_comment_panel():
        """Find the scrollable comment panel element (not <html>).

        Returns the Selenium WebElement or None.
        """
        try:
            panel = driver.execute_script("""
                var best = null, bestH = 0;
                var all = document.querySelectorAll('div, ul, section');
                for (var el of all) {
                    var s = window.getComputedStyle(el);
                    if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflowY === 'overlay')
                        && el.scrollHeight > el.clientHeight + 50
                        && el.scrollHeight > bestH) {
                        best = el; bestH = el.scrollHeight;
                    }
                }
                return best;
            """)
            return panel
        except Exception:
            return None

    def _scroll_container():
        """Scroll the comment panel to trigger Instagram's lazy-load.

        Uses step-scroll → near-bottom → bottom → event dispatch technique
        that proved to work in debug_scroll2 (14→66 on 81-comment reel).
        """
        panel = _find_comment_panel()
        if not panel:
            return
        try:
            # Step 1: incremental scroll to bottom
            driver.execute_script("""
                var c = arguments[0];
                var step = c.clientHeight * 0.8;
                var pos = c.scrollTop;
                for (var i = 0; i < 5; i++) { pos += step; c.scrollTop = pos; }
                c.scrollTop = c.scrollHeight;
            """, panel)
            time.sleep(1.5)
            # Step 2: scroll near-bottom then snap to bottom (triggers re-render)
            driver.execute_script("""
                var c = arguments[0];
                c.scrollTop = c.scrollHeight - c.clientHeight - 50;
            """, panel)
            time.sleep(0.5)
            driver.execute_script("""
                var c = arguments[0];
                c.scrollTop = c.scrollHeight;
            """, panel)
            time.sleep(2.0)
            # Step 3: dispatch scroll events
            driver.execute_script("""
                var c = arguments[0];
                c.dispatchEvent(new Event('scroll', {bubbles: true}));
                c.dispatchEvent(new Event('scrollend', {bubbles: true}));
            """, panel)
            time.sleep(1.0)
        except Exception:
            pass

    def _scroll_up_down_sweep():
        """Scroll from top to bottom in steps — sometimes unlocks stuck lazy-loads."""
        panel = _find_comment_panel()
        if not panel:
            return
        try:
            driver.execute_script("arguments[0].scrollTop = 0;", panel)
            time.sleep(0.5)
            driver.execute_script("""
                var c = arguments[0];
                var step = c.clientHeight;
                for (var pos = 0; pos < c.scrollHeight; pos += step) {
                    c.scrollTop = pos;
                }
                c.scrollTop = c.scrollHeight;
                c.dispatchEvent(new Event('scroll', {bubbles: true}));
                c.dispatchEvent(new Event('scrollend', {bubbles: true}));
            """, panel)
        except Exception:
            pass

    def _click_main_expand_buttons() -> bool:
        """Click any 'Ver más comentarios' type buttons. Returns True if clicked."""
        clicked = False
        for _ in range(10):
            main_btn = None
            for sel in SELECTORS:
                try:
                    for el in driver.find_elements("css selector", sel):
                        txt = (el.text or "").strip()
                        if not txt or len(txt) > 80:
                            continue
                        if txt == "+" and sel not in ("div[role='button']",):
                            continue
                        if _MAIN_EXPAND.search(txt) and not _HIDE.search(txt):
                            main_btn = el
                            break
                except Exception:
                    continue
                if main_btn:
                    break
            if not main_btn:
                break
            try:
                main_btn.click()
                clicked = True
                time.sleep(2.0)
                _scroll_container()
                time.sleep(1.0)
            except Exception:
                break
        return clicked

    def _click_reply_buttons() -> int:
        """Click all 'Ver las N respuestas' buttons. Returns count clicked."""
        count = 0
        reply_buttons = []
        for sel in SELECTORS:
            try:
                for el in driver.find_elements("css selector", sel):
                    txt = (el.text or "").strip()
                    if txt and len(txt) < 80 and _REPLY_EXPAND.search(txt) and not _HIDE.search(txt):
                        reply_buttons.append(el)
            except Exception:
                continue
        for btn in reply_buttons:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.3)
                btn.click()
                count += 1
                time.sleep(1.0)
            except Exception:
                continue
        return count

    def _click_hidden_comments() -> bool:
        """Click 'Ver comentarios ocultos' if present."""
        clicked = False
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, "svg[aria-label='Ver comentarios ocultos']"):
                try:
                    parent = el.find_element(By.XPATH, "./..")
                    parent.click()
                    clicked = True
                    time.sleep(2.0)
                except Exception:
                    pass
        except Exception:
            pass
        return clicked

    # ------------------------------------------------------------------
    prev_count = _count_permalinks()
    stale_rounds = 0
    MAX_STALE = 8  # patience: 8 rounds with no growth before stopping

    for round_num in range(max_rounds):
        # 1) SCROLL the comment panel (primary expansion mechanism)
        _scroll_container()
        time.sleep(2.0)

        # 2) Click main expand buttons if any exist (non-reel pages)
        _click_main_expand_buttons()

        # 3) Click reply-expand buttons
        _click_reply_buttons()

        # 4) Click hidden-comments button
        _click_hidden_comments()

        # 5) Scroll again after clicks to load more
        _scroll_container()
        time.sleep(2.0)

        # 6) Check progress
        cur_count = _count_permalinks()
        if cur_count > prev_count:
            log.debug("  [r%d] permalinks: %d -> %d", round_num, prev_count, cur_count)
            prev_count = cur_count
            stale_rounds = 0
        else:
            stale_rounds += 1

        # 7) If stale for 4 rounds, try a full up-down sweep
        if stale_rounds == 4:
            _scroll_up_down_sweep()
            time.sleep(3.0)
            sweep_count = _count_permalinks()
            if sweep_count > prev_count:
                prev_count = sweep_count
                stale_rounds = 0
                continue

        if stale_rounds >= MAX_STALE:
            log.debug("  [r%d] no new comments for %d rounds, stopping", round_num, MAX_STALE)
            break


def _extract_comments(driver, caption: str) -> list[dict]:
    """Extract ALL comments using the permalink-based approach (Instagram 2026 DOM)."""
    from selenium.webdriver.common.by import By

    comments: list[dict] = []
    seen_texts: set[str] = set()

    _COMMENT_PERMALINK = re.compile(r"/p/[^/]+/c/\d+/|/reel/[^/]+/c/\d+/")
    _USERNAME_HREF = re.compile(r"^/[a-zA-Z0-9_.]+/$")
    _USERNAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{1,29}$")

    try:
        permalink_links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
        for plink in permalink_links:
            href = (plink.get_attribute("href") or "")
            if not _COMMENT_PERMALINK.search(href):
                continue

            try:
                container = plink.find_element(By.XPATH, "./../../..")
            except Exception:
                continue

            # Username
            usuario = None
            try:
                anchors = container.find_elements(By.CSS_SELECTOR, "a[href]")
                for a in anchors:
                    a_href = a.get_attribute("href") or ""
                    a_text = (a.text or "").strip()
                    if a_text and _USERNAME_PATTERN.match(a_text):
                        path = urlparse(a_href).path
                        if _USERNAME_HREF.match(path):
                            usuario = a_text
                            break
            except Exception:
                pass

            # Comment text
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
    except Exception as exc:
        log.debug("Error extrayendo comentarios: %s", exc)

    return comments


def _scrape_comments_for_url(driver, url: str, caption: str) -> list[dict]:
    """Navigate to a post URL and extract its comments."""
    try:
        driver.get(url)
    except Exception:
        log.warning("Timeout cargando %s", url)
    time.sleep(3.0)

    # Expand all comments + replies (multiple rounds)
    _expand_comments(driver, max_rounds=80)
    time.sleep(2.0)

    return _extract_comments(driver, caption)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enriquecer JSON de Instagram con comentarios")
    parser.add_argument("--file", type=Path, default=DEFAULT_JSON,
                        help="Ruta al JSON de posts (default: %(default)s)")
    parser.add_argument("--cookies", type=Path, default=DEFAULT_COOKIES,
                        help="Archivo de cookies Netscape")
    parser.add_argument("--max", type=int, default=0,
                        help="Max posts a procesar (0 = todos)")
    parser.add_argument("--max-comments", type=int, default=MAX_COMMENTS,
                        help="Max comentarios por post")
    parser.add_argument("--all", action="store_true",
                        help="Re-extraer comentarios incluso si ya tiene")
    args = parser.parse_args()

    # --- Load JSON ---
    json_path: Path = args.file
    if not json_path.exists():
        log.error("No se encontró %s", json_path)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        posts: list[dict] = json.load(f)
    log.info("Cargados %d posts desde %s", len(posts), json_path)

    # --- Filter posts that need comments ---
    if args.all:
        to_process = [p for p in posts if _reported_comment_count(p) != 0]
    else:
        to_process = [p for p in posts
                      if (not p.get("comments") or len(p.get("comments", [])) == 0)
                      and _reported_comment_count(p) != 0]

    skipped = len(posts) - len(to_process)
    if skipped:
        log.info("Skipped %d posts con 0 comentarios reportados", skipped)

    if args.max > 0:
        to_process = to_process[:args.max]

    if not to_process:
        log.info("Todos los posts ya tienen comentarios. Usa --all para re-extraer.")
        return

    log.info("Posts a enriquecer: %d / %d", len(to_process), len(posts))

    # --- Build URL-to-index map ---
    url_to_indices: dict[str, list[int]] = {}
    for idx, p in enumerate(posts):
        url = p.get("url_noticia", "")
        if url:
            url_to_indices.setdefault(url, []).append(idx)

    # --- Start Selenium ---
    driver = _create_driver()
    _load_cookies(driver, args.cookies)

    enriched = 0
    total_comments = 0
    try:
        for i, post in enumerate(to_process, 1):
            url = post.get("url_noticia", "")
            if not url:
                continue

            caption = post.get("raw_text") or post.get("description_text") or ""
            log.info("[%d/%d] Extrayendo comentarios: %s", i, len(to_process), url[:80])

            comments = _scrape_comments_for_url(driver, url, caption)

            if comments:
                log.info("  -> %d comentarios extraídos", len(comments))
                total_comments += len(comments)
            else:
                log.info("  -> 0 comentarios")

            # Update all matching entries in the posts list
            comments_text = [c["texto"] for c in comments if c.get("texto")]
            for idx in url_to_indices.get(url, []):
                posts[idx]["comments"] = comments
                posts[idx]["n_comments"] = len(comments)
                posts[idx]["comments_text"] = comments_text
            enriched += 1

            # Save incrementally every 10 posts
            if enriched % 10 == 0:
                _save_json(posts, json_path)
                log.info("  [checkpoint] Guardado parcial: %d posts procesados", enriched)

    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario. Guardando progreso...")
    finally:
        # Always save on exit
        _save_json(posts, json_path)
        log.info("=== Resultado: %d posts enriquecidos, %d comentarios totales ===", enriched, total_comments)
        try:
            driver.quit()
        except Exception:
            pass


def _save_json(posts: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
    log.info("JSON guardado: %s (%d posts)", path, len(posts))


if __name__ == "__main__":
    main()
