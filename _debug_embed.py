"""Debug: Test Instagram embed endpoint and profile page access."""
import time
import re
from src.scrapers.selenium_scraper import SeleniumScraper

s = SeleniumScraper(timeout_seconds=30, headless=True)
d = s._driver_instance()

# Test 1: Embed endpoint (usually public)
print("=== TEST 1: EMBED ENDPOINT ===")
d.get("https://www.instagram.com/p/DHlBp3luP_W/embed/")
time.sleep(6)
info = d.execute_script("""
    var vids = document.querySelectorAll('video');
    var caption = document.querySelector('.Caption, .CaptionUsername, [class*=Caption]');
    var comments = document.querySelectorAll('.Comment, [class*=Comment]');
    return {
        videoCount: vids.length,
        title: document.title,
        bodyLen: document.body.innerText.length,
        captionText: caption ? caption.innerText.substring(0, 200) : 'NO CAPTION'
    };
""")
print("Embed info:", info)
body = d.execute_script("return document.body.innerText.substring(0, 600)")
print("Embed body:", body[:400])

# Check for video in embed
vid_info = d.execute_script("""
    var vids = document.querySelectorAll('video');
    var result = [];
    vids.forEach(function(v) {
        result.push({src: v.src || v.currentSrc || '', poster: v.poster || ''});
    });
    return result;
""")
print("Video tags in embed:", vid_info)

# Check for video URL in embed HTML
embed_html = d.page_source
vid_patterns = re.findall(r'"(https://[^"]*(?:cdninstagram|fbcdn)[^"]*\.mp4[^"]*)"', embed_html)
print("CDN video URLs:", len(vid_patterns))
if vid_patterns:
    print("  First:", vid_patterns[0][:150])

# Look for video_url pattern
vurl = re.findall(r'"video_url":"([^"]+)"', embed_html)
print("video_url pattern:", len(vurl))

# Save embed HTML
with open("_debug_embed.html", "w", encoding="utf-8") as f:
    f.write(embed_html)
print(f"Embed HTML saved: {len(embed_html)} chars")

# Test 2: Profile page (usually public)
print("\n=== TEST 2: PROFILE PAGE ===")
d.get("https://www.instagram.com/alertacalidad/")
time.sleep(8)
prof_info = d.execute_script("""
    var links = document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]');
    var articles = document.querySelectorAll('article');
    return {
        postLinks: links.length,
        articles: articles.length,
        title: document.title,
        bodyLen: document.body.innerText.length
    };
""")
print("Profile info:", prof_info)
prof_body = d.execute_script("return document.body.innerText.substring(0, 400)")
print("Profile body:", prof_body[:300])

s.close()
