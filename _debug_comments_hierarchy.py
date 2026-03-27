"""Debug: extract the exact tag hierarchy around comment blocks."""
import re
from bs4 import BeautifulSoup

with open("_debug_page_source.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Each comment has a link like /p/POSTID/c/COMMENTID/
comment_links = soup.find_all("a", href=re.compile(r"/p/[^/]+/c/\d+/"))
print(f"Found {len(comment_links)} comment links\n")

for i, link in enumerate(comment_links):
    print(f"=== Comment #{i} ===")
    print(f"  href: {link.get('href')}")
    
    # Get the parent container — go up until we find a meaningful block
    container = link
    for _ in range(10):
        if container.parent:
            container = container.parent
        # Stop when we find a div that seems like the comment container
        siblings = container.find_all("a", href=re.compile(r"/[a-zA-Z0-9_.]+/$"))
        if siblings:
            break
    
    # Now find the username link (href like /username/)
    user_links = container.find_all("a", href=re.compile(r"^/[a-zA-Z0-9_.]+/$"))
    for ul in user_links:
        username_text = ul.get_text(strip=True)
        if username_text:
            print(f"  username: {username_text} (href={ul.get('href')})")
    
    # Find span[dir=auto] for comment text
    spans_auto = container.find_all("span", attrs={"dir": "auto"})
    for s in spans_auto:
        txt = s.get_text(strip=True)
        if txt and len(txt) > 3 and txt not in ("Responder", "Reply") and "Me gusta" not in txt:
            # Skip if it matches a username
            if not re.match(r"^[a-zA-Z0-9_.]+$", txt):
                print(f"  text: {txt[:120]}")
    
    # Show tag hierarchy from comment_link up to root
    hierarchy = []
    p = link
    for _ in range(15):
        if p:
            attrs = ""
            if p.get("role"):
                attrs += f' role={p["role"]}'
            hierarchy.append(f"{p.name}{attrs}")
            p = p.parent
    print(f"  hierarchy: {' < '.join(hierarchy)}")
    print()
