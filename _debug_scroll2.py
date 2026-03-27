"""Debug v2: aggressive scroll to load ALL comments on reel."""
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
time.sleep(6)

_PERMALINK = re.compile(r"/p/[^/]+/c/\d+/|/reel/[^/]+/c/\d+/")

def count_comments():
    links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
    return sum(1 for l in links if _PERMALINK.search(l.get_attribute("href") or ""))

print(f"Initial: {count_comments()} comments")

# Get the comment panel container selector
CONTAINER_SEL = "div.x5yr21d.xw2csxc.x1odjw0f.x1n2onr6"

stale_count = 0
MAX_STALE = 8  # more patience before giving up
prev = count_comments()

for rnd in range(60):
    # --- Strategy 1: incremental scroll within container ---
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{
            // Scroll in steps rather than jumping to bottom
            var step = c.clientHeight * 0.8;
            var pos = c.scrollTop;
            for (var i = 0; i < 5; i++) {{
                pos += step;
                c.scrollTop = pos;
            }}
            // Then jump to absolute bottom
            c.scrollTop = c.scrollHeight;
        }}
    """)
    time.sleep(1.5)
    
    # --- Strategy 2: scroll up then back down to trigger re-render ---
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{
            c.scrollTop = c.scrollHeight - c.clientHeight - 50;
        }}
    """)
    time.sleep(0.5)
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{ c.scrollTop = c.scrollHeight; }}
    """)
    time.sleep(2.0)
    
    # --- Strategy 3: dispatch scroll event manually ---
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{
            c.dispatchEvent(new Event('scroll', {{bubbles: true}}));
            c.dispatchEvent(new Event('scrollend', {{bubbles: true}}));
        }}
    """)
    time.sleep(1.0)
    
    # --- Click reply buttons ---
    reply_clicked = 0
    for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
        text = (el.text or "").strip().lower()
        if "respuesta" in text and "ocultar" not in text and "ver" in text:
            try:
                el.click()
                reply_clicked += 1
                time.sleep(0.8)
            except:
                pass
    
    cur = count_comments()
    
    # Get scroll info
    info = driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) return {{top: c.scrollTop, height: c.scrollHeight, client: c.clientHeight}};
        return null;
    """)
    
    print(f"  round {rnd}: {prev} -> {cur} (replies_clicked={reply_clicked}) scroll={info}")
    
    if cur > prev:
        stale_count = 0
    else:
        stale_count += 1
    prev = cur
    
    if stale_count >= MAX_STALE:
        print(f"  Stale for {MAX_STALE} rounds, stopping.")
        break

print(f"\nFINAL: {count_comments()} comments")

# Also: let's check if there's a spinner/loading indicator
spinners = driver.execute_script("""
    var result = [];
    // Check for loading spinners (SVG circles are common)
    var svgs = document.querySelectorAll('svg[aria-label]');
    for (var s of svgs) {
        result.push(s.getAttribute('aria-label'));
    }
    // Check for any "loading" role or aria
    var loading = document.querySelectorAll('[role="progressbar"], [aria-busy="true"]');
    for (var l of loading) {
        result.push('progressbar/busy: ' + l.tagName);
    }
    return result;
""")
print(f"Spinners/loading: {spinners}")

driver.quit()
print("DONE")
