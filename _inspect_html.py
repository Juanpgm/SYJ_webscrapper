import re
html = open("_debug_page_source.html", "r", encoding="utf-8").read()
canon = re.findall(r'rel=.canonical. href="([^"]+)"', html)
og_url = re.findall(r'og:url. content="([^"]+)"', html)
title_m = re.findall(r"<title>(.+?)</title>", html)
print("canonical:", canon[:2])
print("og_url:", og_url[:2])
print("title:", title_m[:1])
print("has <article>:", "<article" in html)
print("html len:", len(html))
login_wall = "login" in html[:5000].lower() or "inicia sesión" in html[:5000].lower()
print("login wall:", login_wall)

# Check for key DOM elements
print("\n--- DOM elements ---")
print("article count:", html.count("<article"))
print("ul count:", html.count("<ul"))
print("li count:", html.count("<li"))
print("span dir=auto:", html.count('dir="auto"'))
print("time[datetime]:", len(re.findall(r'<time[^>]*datetime', html)))
print("header count:", html.count("<header"))

# Check for comment-related text
print("\n--- Comment indicators ---")
print("'comentario':", html.lower().count("comentario"))
print("'comment':", html.lower().count("comment"))
print("'Ver todos':", html.lower().count("ver todos"))
print("'View all':", html.lower().count("view all"))

# Find any span with dir=auto and show their text
spans = re.findall(r'<span[^>]*dir="auto"[^>]*>([^<]{3,200})</span>', html)
print(f"\n--- span[dir=auto] texts ({len(spans)} total) ---")
for i, s in enumerate(spans[:15]):
    print(f"  {i+1}. {s[:120]}")
