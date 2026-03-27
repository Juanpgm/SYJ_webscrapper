"""Debug: extract comments using the permalink pattern."""
import re
from bs4 import BeautifulSoup

with open("_debug_page_source.html", "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Each comment has a timestamp link like /p/POSTID/c/COMMENTID/
comment_links = soup.find_all("a", href=re.compile(r"/p/[^/]+/c/\d+/"))
print(f"Found {len(comment_links)} comment permalink links\n")

for i, clink in enumerate(comment_links):
    # Go up N levels to find the comment container div
    for levels in range(3, 12):
        container = clink
        for _ in range(levels):
            if container.parent:
                container = container.parent
        
        # Check if this container has a username link
        user_link = container.find("a", href=re.compile(r"^/[a-zA-Z0-9_.]+/$"))
        if user_link:
            username = user_link.get_text(strip=True)
            if username and re.match(r"^[a-zA-Z0-9_.]+$", username):
                # Found username - now find comment text
                spans = container.find_all("span", attrs={"dir": "auto"})
                texts = []
                for s in spans:
                    txt = s.get_text(strip=True)
                    if (txt and len(txt) > 3 
                        and txt != username 
                        and txt not in ("Responder", "Reply")
                        and "Me gusta" not in txt
                        and "like" not in txt.lower()):
                        texts.append(txt)
                
                print(f"Comment #{i} (levels_up={levels}):")
                print(f"  username: {username}")
                print(f"  texts: {texts}")
                print(f"  container tag: {container.name}")
                
                # Show immediate children of container
                children = list(container.children)
                child_tags = [c.name for c in children if c.name]
                print(f"  container children: {child_tags}")
                print()
                break
    else:
        print(f"Comment #{i}: Could not find container with username link")
