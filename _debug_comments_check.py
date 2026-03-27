"""Quick debug: check if Instagram comments load in headless Selenium."""
import time
import re
import http.cookiejar
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

# Load cookies
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

# Check session
cookies_str = str(driver.get_cookies())
if "ds_user_id" in cookies_str:
    print("SESSION: ACTIVE")
else:
    print("SESSION: NOT ACTIVE")

# Go to a post with 72 reported comments
url = "https://www.instagram.com/cali_informa/p/DWRGljVFsko/"
print(f"Loading: {url}")
driver.get(url)
time.sleep(5)

# Page title
print(f"Page title: {driver.title}")

# Login wall check
src_lower = driver.page_source[:5000].lower()
if "login" in src_lower and "accounts/login" in src_lower:
    print("WARNING: Login wall detected!")
else:
    print("No login wall in first 5k chars")

# Comment permalink links
links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
comment_links = []
for lnk in links:
    href = lnk.get_attribute("href") or ""
    if re.search(r"/p/[^/]+/c/\d+/", href) or re.search(r"/reel/[^/]+/c/\d+/", href):
        comment_links.append(href)
print(f"Comment permalink links found: {len(comment_links)}")
for cl in comment_links[:5]:
    print(f"  {cl}")

# Span elements
spans = driver.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
print(f"Total span[dir='auto'] elements: {len(spans)}")
texts_found = 0
for s in spans:
    t = (s.text or "").strip()
    if t and len(t) > 5:
        texts_found += 1
        if texts_found <= 8:
            print(f"  span: {t[:100]}")
print(f"Spans with text > 5 chars: {texts_found}")

# Try expand button
SELECTORS = ["div[role='button']", "span[role='link']", "button"]
for sel in SELECTORS:
    for el in driver.find_elements(By.CSS_SELECTOR, sel):
        text = (el.text or "").strip()
        if text and ("comentario" in text.lower() or "comment" in text.lower() or "respuesta" in text.lower()):
            print(f"  EXPAND BUTTON [{sel}]: '{text}'")

driver.quit()
print("DONE")
