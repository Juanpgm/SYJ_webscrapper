"""Test: run enrichment on one specific high-comment post."""
import json
import logging
import time
from enrich_comments import (
    _create_driver, _load_cookies, _expand_comments, _extract_comments,
)
from pathlib import Path

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

TEST_URL = "https://www.instagram.com/ultimahoracalioficial/reel/DWPX83nkdls/"

driver = _create_driver()
_load_cookies(driver, Path("config/instagram_cookies.txt"))

log.info("Loading %s", TEST_URL)
driver.get(TEST_URL)
time.sleep(5)

log.info("Expanding comments...")
_expand_comments(driver, max_rounds=80)
time.sleep(2)

log.info("Extracting comments...")
comments = _extract_comments(driver, caption="")

log.info("=== RESULT: %d comments extracted ===", len(comments))
for i, c in enumerate(comments[:5], 1):
    log.info("  [%d] @%s: %s", i, c.get("usuario"), (c.get("texto") or "")[:80])
if len(comments) > 5:
    log.info("  ... and %d more", len(comments) - 5)

driver.quit()
