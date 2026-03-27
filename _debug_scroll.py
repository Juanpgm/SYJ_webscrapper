"""Debug: find the scrollable comment container and scroll to load all comments."""
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

_PERMALINK = re.compile(r"/p/[^/]+/c/\d+/|/reel/[^/]+/c/\d+/")

def count_comments():
    links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
    return sum(1 for l in links if _PERMALINK.search(l.get_attribute("href") or ""))

print(f"Initial comments: {count_comments()}")

# Find ALL scrollable containers and try scrolling each one
print("\n=== Finding scrollable containers ===")
containers = driver.execute_script("""
    var result = [];
    var all = document.querySelectorAll('*');
    for (var el of all) {
        var style = window.getComputedStyle(el);
        var overflowY = style.overflowY;
        if ((overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') 
            && el.scrollHeight > el.clientHeight + 50) {
            result.push({
                tag: el.tagName,
                className: el.className.substring(0, 80),
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
                children: el.children.length
            });
        }
    }
    return result;
""")
for i, c in enumerate(containers):
    print(f"  [{i}] <{c['tag']}> class='{c['className'][:50]}' scrollH={c['scrollHeight']} clientH={c['clientHeight']} children={c['children']}")

# Now try scrolling the containers that look like comment panels
print("\n=== Scrolling containers to load more comments ===")
for scroll_round in range(20):
    before = count_comments()
    
    # Scroll ALL overflow containers
    driver.execute_script("""
        var all = document.querySelectorAll('*');
        for (var el of all) {
            var style = window.getComputedStyle(el);
            var overflowY = style.overflowY;
            if ((overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') 
                && el.scrollHeight > el.clientHeight + 50) {
                el.scrollTop = el.scrollHeight;
            }
        }
        window.scrollBy(0, 1000);
    """)
    time.sleep(2.0)
    
    # Also click any reply expand buttons
    for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
        text = (el.text or "").strip().lower()
        if "respuesta" in text and "ocultar" not in text:
            try:
                el.click()
                time.sleep(1.0)
            except:
                pass
    
    after = count_comments()
    print(f"  round {scroll_round}: {before} -> {after} comments")
    
    if after == before and scroll_round > 3:
        # Try one more aggressive scroll approach
        driver.execute_script("""
            var all = document.querySelectorAll('ul');
            for (var el of all) {
                if (el.scrollHeight > el.clientHeight) {
                    el.scrollTop = el.scrollHeight;
                }
            }
        """)
        time.sleep(2.0)
        final = count_comments()
        if final == after:
            print(f"  Stabilized at {final} comments after round {scroll_round}")
            break

final_count = count_comments()
print(f"\nFINAL: {final_count} comments extracted")

driver.quit()
print("DONE")
