"""Debug v3: scroll + hidden comments + full sweep."""
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
CONTAINER_SEL = "div.x5yr21d.xw2csxc.x1odjw0f.x1n2onr6"

def count_comments():
    links = driver.find_elements(By.CSS_SELECTOR, "a[role='link']")
    return sum(1 for l in links if _PERMALINK.search(l.get_attribute("href") or ""))

def scroll_container():
    """Scroll the comment container to bottom in steps."""
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{
            var step = c.clientHeight * 0.7;
            for (var i = 0; i < 8; i++) {{
                c.scrollTop += step;
            }}
            c.scrollTop = c.scrollHeight;
            c.dispatchEvent(new Event('scroll', {{bubbles: true}}));
        }}
    """)

def scroll_up_down():
    """Scroll from top to bottom in steps to trigger lazy loading."""
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{
            c.scrollTop = 0;
        }}
    """)
    time.sleep(0.5)
    driver.execute_script(f"""
        var c = document.querySelector('{CONTAINER_SEL}');
        if (c) {{
            var step = c.clientHeight;
            var max = c.scrollHeight;
            for (var pos = 0; pos < max; pos += step) {{
                c.scrollTop = pos;
            }}
            c.scrollTop = max;
            c.dispatchEvent(new Event('scroll', {{bubbles: true}}));
        }}
    """)

def click_reply_buttons():
    """Click all 'Ver las N respuestas' buttons."""
    count = 0
    for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button']"):
        text = (el.text or "").strip().lower()
        if "respuesta" in text and "ocultar" not in text and "ver" in text:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.3)
                el.click()
                count += 1
                time.sleep(1.0)
            except:
                pass
    return count

def click_hidden_comments():
    """Click 'Ver comentarios ocultos' button."""
    count = 0
    # Try by aria-label
    for el in driver.find_elements(By.CSS_SELECTOR, "svg[aria-label='Ver comentarios ocultos']"):
        try:
            parent = el.find_element(By.XPATH, "./..")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", parent)
            time.sleep(0.3)
            parent.click()
            count += 1
            time.sleep(2.0)
            print(f"  >> Clicked 'Ver comentarios ocultos' (via svg parent)")
        except Exception as e:
            print(f"  >> Failed to click hidden comments svg: {e}")
    
    # Also try by text in any button/div
    for el in driver.find_elements(By.CSS_SELECTOR, "div[role='button'], button, span"):
        text = (el.text or "").strip().lower()
        if "oculto" in text or "hidden" in text:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                time.sleep(0.3)
                el.click()
                count += 1
                time.sleep(2.0)
                print(f"  >> Clicked hidden comments element: '{el.text}'")
            except:
                pass
    return count

print(f"Initial: {count_comments()} comments")

stale_count = 0
MAX_STALE = 10
prev = count_comments()

for rnd in range(80):
    # Phase 1: Scroll to bottom
    scroll_container()
    time.sleep(2.0)
    
    # Phase 2: Click reply buttons
    reply_clicks = click_reply_buttons()
    
    # Phase 3: Click hidden comments
    hidden_clicks = click_hidden_comments()
    
    # Phase 4: Scroll back to bottom after clicks
    scroll_container()
    time.sleep(2.0)
    
    cur = count_comments()
    print(f"  round {rnd}: {prev} -> {cur} (replies={reply_clicks}, hidden={hidden_clicks})")
    
    if cur > prev:
        stale_count = 0
    else:
        stale_count += 1
    prev = cur
    
    # After being stale for a while, try full sweep
    if stale_count == 4:
        print("  >> Trying full up-down sweep...")
        scroll_up_down()
        time.sleep(3.0)
        new = count_comments()
        if new > cur:
            stale_count = 0
            prev = new
            print(f"  >> Sweep found more: {cur} -> {new}")
            continue
    
    if stale_count >= MAX_STALE:
        print(f"  Stale for {MAX_STALE} rounds, stopping.")
        break

final = count_comments()
print(f"\nFINAL: {final} comments")

driver.quit()
print("DONE")
