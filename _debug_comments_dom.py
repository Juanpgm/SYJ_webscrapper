"""Debug: extract comment DOM structure from saved page source."""
import re

with open("_debug_page_source.html", "r", encoding="utf-8") as f:
    content = f.read()

# Find all 'Responder' occurrences and extract the comment block 
positions = [m.start() for m in re.finditer("Responder", content)]
print(f"Found {len(positions)} 'Responder' occurrences\n")

for idx, pos in enumerate(positions):
    start = max(0, pos - 4000)
    end = min(len(content), pos + 100)
    chunk = content[start:end]
    
    hrefs = re.findall(r'href="([^"]+)"', chunk)
    spans = re.findall(r'<span[^>]*>([^<]+)</span>', chunk)
    
    print(f"=== Comment block #{idx} ===")
    print("Hrefs:")
    for h in hrefs:
        if "/instagram.com/" not in h and not h.startswith("#") and not h.startswith("https://static"):
            print(f"  {h}")
    
    print("Span texts (non-empty, len>2):")
    for t in spans:
        t = t.strip()
        if t and len(t) > 2 and not t.startswith("x") and "class" not in t.lower():
            print(f"  [{len(t)}] {t[:120]}")
    print()
