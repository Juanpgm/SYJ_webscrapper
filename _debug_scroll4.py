"""Debug: check what scrollable containers the JS finds, and manually scroll."""
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
driver.set_script_timeout(30)

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

# Check what JS sees
containers = driver.execute_script("""
    var result = [];
    var all = document.querySelectorAll('*');
    for (var el of all) {
        var s = window.getComputedStyle(el);
        if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflowY === 'overlay')
            && el.scrollHeight > el.clientHeight + 50) {
            result.push({
                tag: el.tagName,
                cls: el.className.substring(0, 100),
                scrollH: el.scrollHeight,
                clientH: el.clientHeight,
                overflowY: s.overflowY,
                scrollTop: el.scrollTop
            });
        }
    }
    return result;
""")
print(f"\nScrollable containers found: {len(containers)}")
for i, c in enumerate(containers):
    print(f"  [{i}] <{c['tag']}> overflow={c['overflowY']} scrollH={c['scrollH']} clientH={c['clientH']} cls='{c['cls'][:60]}'")

# Now try the EXACT same JS as enrich_comments.py uses
print("\n=== Testing enrich_comments.py scroll JS ===")
result = driver.execute_script("""
    var scrolled = 0;
    var all = document.querySelectorAll('*');
    for (var el of all) {
        var s = window.getComputedStyle(el);
        if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflowY === 'overlay')
            && el.scrollHeight > el.clientHeight + 50) {
            var step = el.clientHeight * 0.7;
            for (var i = 0; i < 8; i++) { el.scrollTop += step; }
            el.scrollTop = el.scrollHeight;
            el.dispatchEvent(new Event('scroll', {bubbles: true}));
            scrolled++;
        }
    }
    window.scrollBy(0, 800);
    return scrolled;
""")
print(f"Containers scrolled: {result}")
time.sleep(3)
print(f"After first scroll: {count_comments()} comments")

# Scroll multiple rounds
for rnd in range(15):
    driver.execute_script("""
        var all = document.querySelectorAll('*');
        for (var el of all) {
            var s = window.getComputedStyle(el);
            if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflowY === 'overlay')
                && el.scrollHeight > el.clientHeight + 50) {
                var step = el.clientHeight * 0.7;
                for (var i = 0; i < 8; i++) { el.scrollTop += step; }
                el.scrollTop = el.scrollHeight;
                el.dispatchEvent(new Event('scroll', {bubbles: true}));
            }
        }
        window.scrollBy(0, 800);
    """)
    time.sleep(2.5)
    
    # Click replies
    for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
        text = (el.text or "").strip().lower()
        if "respuesta" in text and "ocultar" not in text and "ver" in text:
            try: el.click(); time.sleep(0.8)
            except: pass
    
    print(f"  round {rnd}: {count_comments()} comments")

print(f"\nFINAL: {count_comments()}")
driver.quit()
