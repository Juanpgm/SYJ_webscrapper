"""Debug: simulate _extract_comments step by step to see what gets filtered."""
import time, re, http.cookiejar
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from urllib.parse import urlparse

# --- Junk filter from enrich_comments.py ---
_COMMENT_JUNK_PATTERNS = re.compile(
    r"^(\d+\s*[hmdws]|\d+\s*h(ora)?s?|\d+\s*d(ía)?s?|\d+\s*sem|\d+\s*min"
    r"|me gusta|likes?|responder|reply|publicidad|patrocinado|sponsored"
    r"|ver\s+\d+\s+respuesta|view\s+\d+\s+repl"
    r"|más|more|\.\.\.|…|ver\s+traducción|see\s+translation"
    r"|enviar|send|respuesta|contestar)$",
    re.IGNORECASE,
)

def _is_junk_text(text, caption, author):
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

# --- Setup driver ---
options = uc.ChromeOptions()
options.add_argument("--headless=new")
options.add_argument("--window-size=1366,768")
options.add_argument("--no-sandbox")
options.add_argument("--lang=es-CO")
options.add_argument("--mute-audio")
driver = uc.Chrome(options=options)
driver.set_page_load_timeout(20)

driver.get("https://www.instagram.com/")
time.sleep(2)
cj = http.cookiejar.MozillaCookieJar("config/instagram_cookies.txt")
cj.load(ignore_discard=True, ignore_expires=True)
for c in cj:
    try:
        driver.add_cookie({"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": c.secure})
    except Exception:
        pass
driver.refresh()
time.sleep(2)
print("Session loaded")

# --- Navigate to post ---
url = "https://www.instagram.com/cali_informa/p/DWRGljVFsko/"
driver.get(url)
time.sleep(5)

# --- Simulate _extract_comments ---
_COMMENT_PERMALINK = re.compile(r"/p/[^/]+/c/\d+/|/reel/[^/]+/c/\d+/")
_USERNAME_HREF = re.compile(r"^/[a-zA-Z0-9_.]+/$")
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{1,29}$")

caption = ""  # We'll simulate unknown caption

permalink_links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
print(f"\nTotal a[role='link']: {len(permalink_links)}")

comment_count = 0
for plink in permalink_links:
    href = (plink.get_attribute("href") or "")
    if not _COMMENT_PERMALINK.search(href):
        continue
    comment_count += 1
    print(f"\n--- Comment #{comment_count} ---")
    print(f"  permalink: {href}")

    try:
        container = plink.find_element(By.XPATH, "./../../..")
    except Exception as e:
        print(f"  ERROR getting container: {e}")
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
    print(f"  usuario: {usuario}")

    # All spans in container
    spans = container.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
    print(f"  spans found: {len(spans)}")
    texto_parts = []
    for span in spans:
        t = (span.text or "").strip()
        is_junk = _is_junk_text(t, caption, usuario) if t else True
        if t:
            print(f"    span text: '{t[:80]}' -> junk={is_junk}")
        if t and not is_junk:
            texto_parts.append(t)
    texto = " ".join(texto_parts).strip()
    print(f"  FINAL texto: '{texto[:120]}'")

    if comment_count >= 5:
        print("\n... (showing first 5 only)")
        break

driver.quit()
print("\nDONE")
