"""Debug: check what Instagram renders in headless Selenium."""
import time
from src.scrapers.selenium_scraper import SeleniumScraper

s = SeleniumScraper(timeout_seconds=30, headless=True)
d = s._driver_instance()
d.get("https://www.instagram.com/reel/DHlBp3luP_W/")
time.sleep(12)
d.execute_script("window.scrollTo(0, document.body.scrollHeight * 0.5)")
time.sleep(3)

info = d.execute_script("""
    var vids = document.querySelectorAll('video');
    var articles = document.querySelectorAll('article');
    var spans = document.querySelectorAll('span');
    var longSpans = 0;
    spans.forEach(function(s) { if(s.textContent.length > 20) longSpans++; });
    var dialog = document.querySelector('[role="dialog"]');
    return {
        videoCount: vids.length,
        articleCount: articles.length,
        spanCount: spans.length,
        longSpanCount: longSpans,
        bodyTextLen: document.body.innerText.length,
        title: document.title,
        hasDialog: dialog !== null,
        url: window.location.href
    };
""")
print("DOM info:", info)

body = d.execute_script("return document.body.innerText.substring(0, 1000)")
print("Body text:", body[:600])

# Check if there's a login redirect
print("Current URL:", d.current_url)

# Look for video in network via performance logs
try:
    vid_srcs = d.execute_script("""
        var entries = performance.getEntriesByType('resource');
        var vids = entries.filter(e => e.name.includes('.mp4') || e.name.includes('video'));
        return vids.map(e => e.name).slice(0, 5);
    """)
    print("Video resources:", vid_srcs)
except Exception as e:
    print("Perf log error:", e)

s.close()
