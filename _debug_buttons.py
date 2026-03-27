"""Debug: inspect ALL clickable elements on a post with 81 comments."""
import time, re, http.cookiejar
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

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

url = "https://www.instagram.com/ultimahoracalioficial/reel/DWPX83nkdls/"
print(f"Loading: {url}")
driver.get(url)
time.sleep(5)

# Count initial comment permalinks
_PERMALINK = re.compile(r"/p/[^/]+/c/\d+/|/reel/[^/]+/c/\d+/")
links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
comment_links = [l for l in links if _PERMALINK.search(l.get_attribute("href") or "")]
print(f"\nInitial comment permalinks: {len(comment_links)}")

# Show ALL div[role='button'] and their text
print("\n=== ALL div[role='button'] elements ===")
for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
    text = (el.text or "").strip()
    if text and len(text) < 100:
        print(f"  TEXT: '{text}'")

# Show ALL span[role='link'] elements
print("\n=== ALL span[role='link'] elements ===")
for el in driver.find_elements(By.CSS_SELECTOR, "span[role='link']"):
    text = (el.text or "").strip()
    if text:
        print(f"  TEXT: '{text}'")

# Show ALL button elements
print("\n=== ALL <button> elements ===")
for el in driver.find_elements(By.CSS_SELECTOR, "button"):
    text = (el.text or "").strip()
    aria = el.get_attribute("aria-label") or ""
    if text or aria:
        print(f"  TEXT: '{text}' | ARIA: '{aria}'")

# Look for SVG icons inside buttons that might be "load more" (+ icon)
print("\n=== Elements with aria-label containing 'comment' or 'más' ===")
all_els = driver.find_elements(By.CSS_SELECTOR, "[aria-label]")
for el in all_els:
    aria = (el.get_attribute("aria-label") or "").lower()
    if any(kw in aria for kw in ["comment", "comentario", "más", "more", "load", "cargar"]):
        print(f"  TAG: {el.tag_name} | ARIA: '{el.get_attribute('aria-label')}' | TEXT: '{(el.text or '').strip()[:50]}'")

# Check for pagination-style elements
print("\n=== Look for 'Ver' buttons in all spans ===")
for el in driver.find_elements(By.CSS_SELECTOR, "span"):
    text = (el.text or "").strip().lower()
    if text.startswith("ver ") and len(text) < 60:
        print(f"  '{el.text.strip()}'")

# Try clicking "Ver los 81 comentarios" or similar
print("\n=== Trying to find and click main expand ===")
MAIN_RE = re.compile(r"(ver\s+(todos?\s+)?los?\s+\d+\s+comentario|view\s+all\s+\d+\s+comment|ver\s+m.s\s+comentario)", re.IGNORECASE)
for sel in ["div[role='button']", "span[role='link']", "button", "span", "a"]:
    for el in driver.find_elements(By.CSS_SELECTOR, sel):
        text = (el.text or "").strip()
        if text and MAIN_RE.search(text):
            print(f"  FOUND [{sel}]: '{text}'")
            try:
                el.click()
                print("  -> CLICKED!")
                time.sleep(3)
            except Exception as e:
                print(f"  -> CLICK FAILED: {e}")
            break

# Recount after click
links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
comment_links = [l for l in links if _PERMALINK.search(l.get_attribute("href") or "")]
print(f"\nAfter first expand: {len(comment_links)} comment permalinks")

# Show buttons again after expand
print("\n=== div[role='button'] after expand ===")
for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
    text = (el.text or "").strip()
    if text and len(text) < 100 and ("ver" in text.lower() or "view" in text.lower() or "+" in text or "más" in text.lower()):
        print(f"  TEXT: '{text}'")

driver.quit()
print("\nDONE")
