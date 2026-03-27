"""Quick test: enrich ONE reel with 81 reported comments."""
import json, time, logging
from enrich_comments import _create_driver, _load_cookies, _scrape_comments_for_url
from pathlib import Path

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)s | %(message)s")

url = "https://www.instagram.com/ultimahoracalioficial/reel/DWPX83nkdls/"
caption = ""  # no caption filter needed for test

driver = _create_driver()
_load_cookies(driver, Path("config/instagram_cookies.txt"))

t0 = time.time()
comments = _scrape_comments_for_url(driver, url, caption)
elapsed = time.time() - t0

print(f"\n{'='*60}")
print(f"URL: {url}")
print(f"Comments extracted: {len(comments)}")
print(f"Time: {elapsed:.1f}s")
print(f"{'='*60}")
for i, c in enumerate(comments[:10], 1):
    print(f"  {i}. @{c['usuario']}: {c['texto'][:80]}")
if len(comments) > 10:
    print(f"  ... +{len(comments)-10} more")

driver.quit()
