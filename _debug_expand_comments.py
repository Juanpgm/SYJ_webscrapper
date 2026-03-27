"""Debug: open a known post with comments and inspect the expansion buttons."""
import http.cookiejar
import re
import time
import json
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# --- Setup driver ---
options = uc.ChromeOptions()
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument("--window-size=1366,768")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--lang=es-CO")
options.add_argument("--mute-audio")

driver = uc.Chrome(options=options)
driver.set_page_load_timeout(20)

# --- Load cookies ---
driver.get("https://www.instagram.com/")
time.sleep(2)
cj = http.cookiejar.MozillaCookieJar("config/instagram_cookies.txt")
cj.load(ignore_discard=True, ignore_expires=True)
for c in cj:
    d = {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path, "secure": c.secure}
    if c.expires:
        d["expiry"] = c.expires
    try:
        driver.add_cookie(d)
    except:
        pass
driver.refresh()
time.sleep(2)
print("Session active:", "ds_user_id" in str(driver.get_cookies()))

# --- Navigate to post with 11 comments ---
url = "https://www.instagram.com/zonacnoticiasoficial/reel/DWSTqhbAZx8/"
print(f"\nOpening: {url}")
driver.get(url)
time.sleep(3)

# --- Scan for clickable expansion elements ---
print("\n=== SCANNING CLICKABLE ELEMENTS ===")
for sel in ["a", "span[role='link']", "div[role='button']", "button", "span"]:
    els = driver.find_elements(By.CSS_SELECTOR, sel)
    for el in els:
        text = (el.text or "").strip()
        if text and len(text) < 100:
            # Filter for comment-related text
            tl = text.lower()
            if any(kw in tl for kw in [
                "comentario", "comment", "respuesta", "reply", "replies",
                "ver", "view", "más", "more", "cargar", "load"
            ]):
                tag = el.tag_name
                role = el.get_attribute("role") or ""
                href = (el.get_attribute("href") or "")[:60]
                print(f"  [{sel}] tag={tag} role={role} href={href}")
                print(f"    text: {text}")

# --- Count comment permalinks before expansion ---
links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
comment_re = re.compile(r"/(p|reel)/[^/]+/c/\d+/")
permalink_count = sum(1 for l in links if comment_re.search(l.get_attribute("href") or ""))
print(f"\n=== COMMENT PERMALINKS BEFORE EXPANSION: {permalink_count} ===")

# --- Try clicking "Ver los X comentarios" ---
print("\n=== ATTEMPTING EXPANSION ===")
expand_re = re.compile(
    r"(ver\s+(todos\s+)?los?\s+\d+\s+comentario|view\s+all\s+\d+\s+comment"
    r"|ver\s+m.s\s+comentario|view\s+more\s+comment)",
    re.IGNORECASE,
)
reply_re = re.compile(
    r"(ver\s+(\d+\s+)?respuesta|view\s+(\d+\s+)?repl|ver\s+respuesta)",
    re.IGNORECASE,
)

clicked_main = 0
for sel in ["a", "span[role='link']", "div[role='button']", "button", "span"]:
    try:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            text = (el.text or "").strip()
            if text and expand_re.search(text):
                print(f"  CLICKING EXPAND: '{text}'")
                el.click()
                time.sleep(3)
                clicked_main += 1
    except Exception as e:
        print(f"  Error: {e}")

print(f"  Main expansions clicked: {clicked_main}")

# --- Count after main expansion ---
links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
permalink_count = sum(1 for l in links if comment_re.search(l.get_attribute("href") or ""))
print(f"\n=== COMMENT PERMALINKS AFTER MAIN EXPANSION: {permalink_count} ===")

# --- Now try to scroll the comment panel to load more ---
print("\n=== SCROLLING COMMENT PANEL ===")
# Instagram comments are usually inside a scrollable container
# Try scrolling in the main section or a specific container
for scroll_attempt in range(5):
    driver.execute_script("""
        // Try to find and scroll the comment section
        var containers = document.querySelectorAll('div[style*="overflow"]');
        for (var c of containers) {
            if (c.scrollHeight > c.clientHeight + 100) {
                c.scrollTop = c.scrollHeight;
            }
        }
        // Also try general scroll
        window.scrollBy(0, 500);
    """)
    time.sleep(1.5)

links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
permalink_count = sum(1 for l in links if comment_re.search(l.get_attribute("href") or ""))
print(f"  COMMENT PERMALINKS AFTER SCROLL: {permalink_count}")

# --- Try expanding reply threads ---
print("\n=== EXPANDING REPLIES ===")
clicked_replies = 0
for attempt in range(3):
    for sel in ["span", "div[role='button']", "button", "a", "span[role='link']"]:
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                text = (el.text or "").strip()
                if text and reply_re.search(text):
                    print(f"  CLICKING REPLY: '{text}'")
                    try:
                        el.click()
                        time.sleep(1.5)
                        clicked_replies += 1
                    except:
                        pass
        except:
            pass

print(f"  Reply expansions clicked: {clicked_replies}")

# --- Final count ---
links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
permalink_count = sum(1 for l in links if comment_re.search(l.get_attribute("href") or ""))
print(f"\n=== FINAL COMMENT PERMALINKS: {permalink_count} ===")

# --- Extract and show all comments found ---
print("\n=== EXTRACTED COMMENTS ===")
_USERNAME_HREF = re.compile(r"^/[a-zA-Z0-9_.]+/$")
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]{1,29}$")
from urllib.parse import urlparse

for plink in links:
    href = plink.get_attribute("href") or ""
    if not comment_re.search(href):
        continue
    try:
        container = plink.find_element(By.XPATH, "./../../..")
    except:
        continue
    
    usuario = None
    try:
        for a in container.find_elements(By.CSS_SELECTOR, "a[href]"):
            a_text = (a.text or "").strip()
            a_href = a.get_attribute("href") or ""
            if a_text and _USERNAME_PATTERN.match(a_text):
                path = urlparse(a_href).path
                if _USERNAME_HREF.match(path):
                    usuario = a_text
                    break
    except:
        pass

    spans = container.find_elements(By.CSS_SELECTOR, "span[dir='auto']")
    span_texts = []
    for s in spans:
        t = (s.text or "").strip()
        if t and len(t) > 2:
            span_texts.append(t)
    
    print(f"  @{usuario}: {span_texts}")

# Save page source for analysis
with open("_debug_expand.html", "w", encoding="utf-8") as f:
    f.write(driver.page_source)
print(f"\nPage source saved to _debug_expand.html ({len(driver.page_source)} chars)")

driver.quit()
