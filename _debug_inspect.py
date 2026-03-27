"""Debug script to inspect Instagram HTML for video and comment patterns."""
import re
from bs4 import BeautifulSoup

html = open("_debug_reel.html", "r", encoding="utf-8").read()
soup = BeautifulSoup(html, "lxml")

print("=== VIDEO TAGS ===")
for v in soup.select("video"):
    print("  attrs:", {k: str(v2)[:100] for k, v2 in v.attrs.items()})
    for child in v.children:
        if hasattr(child, "name") and child.name:
            print(f"  child <{child.name}>:", {k: str(v2)[:100] for k, v2 in child.attrs.items()})

print("\n=== OG META ===")
for m in soup.select("meta[property]"):
    prop = m.get("property", "")
    if "video" in prop or "type" in prop:
        print(f"  {prop}: {str(m.get('content',''))[:150]}")

print("\n=== BLOB URLs ===")
blobs = re.findall(r"blob:https?://[^\s\"']+", html)
print(f"  Count: {len(blobs)}")

print("\n=== LD+JSON ===")
for node in soup.select("script[type='application/ld+json']"):
    raw = (node.string or "").strip()
    print(f"  LD+JSON ({len(raw)} chars): {raw[:300]}")

print("\n=== COMMENT-LIKE DOM (article li with spans) ===")
for i, node in enumerate(soup.select("article li")[:5]):
    spans = node.select("span")
    text = " ".join(s.get_text(" ", strip=True)[:80] for s in spans[:2])
    print(f"  [{i}] {text[:150]}")

print("\n=== DIV with comment-like structure ===")
for i, node in enumerate(soup.select("div[role='button'] span, ul span")[:10]):
    text = node.get_text(" ", strip=True)[:100]
    if len(text) > 10:
        print(f"  [{i}] {text}")

print("\n=== xdt__html patterns (new IG) ===")
xdt = re.findall(r"xdt_api__v1__media__shortcode__web_info", html)
print(f"  xdt_api count: {len(xdt)}")

print("\n=== Searching for video src in JS data ===")
# Instagram often stores video in script tags as JSON
for script in soup.select("script"):
    text = script.string or ""
    if "video_versions" in text or "video_url" in text or "playback_url" in text:
        idx = text.find("video_versions") or text.find("video_url") or text.find("playback_url")
        if idx >= 0:
            print(f"  Found video data at pos {idx}: {text[max(0,idx-20):idx+200]}")
            break

# Look for any https CDN video URLs
cdn_patterns = re.findall(
    r'"(https://(?:scontent|video|instagram)[^"]+\.(?:mp4|m4v)[^"]*)"', html
)
print(f"\n=== CDN video URLs: {len(cdn_patterns)} ===")
for u in cdn_patterns[:3]:
    print(f"  {u[:150]}")

# Broader: any URL with video in path
vid_urls = re.findall(r'"(https://[^"]*(?:video|\.mp4|\.m4v)[^"]*)"', html)
print(f"\n=== Broader video URLs: {len(vid_urls)} ===")
for u in vid_urls[:5]:
    print(f"  {u[:150]}")
