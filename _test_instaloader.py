"""Quick test: can instaloader list posts using cookies from Netscape file?"""
import http.cookiejar
import instaloader

COOKIES_FILE = "config/instagram_cookies.txt"

L = instaloader.Instaloader()

# Load Netscape cookies into instaloader's session
cj = http.cookiejar.MozillaCookieJar(COOKIES_FILE)
cj.load(ignore_discard=True, ignore_expires=True)
for cookie in cj:
    L.context._session.cookies.set_cookie(cookie)
print(f"Loaded {len(cj)} cookies")

# Extract sessionid to identify the user
sessionid = L.context._session.cookies.get("sessionid", domain=".instagram.com")
ds_user_id = L.context._session.cookies.get("ds_user_id", domain=".instagram.com")
print(f"ds_user_id={ds_user_id}, sessionid={'present' if sessionid else 'MISSING'}")

try:
    profile = instaloader.Profile.from_username(L.context, "elpaiscali")
    print(f"Profile: {profile.username}, Posts: {profile.mediacount}")
    for i, post in enumerate(profile.get_posts()):
        cap = (post.caption or "")[:80].replace("\n", " ")
        url = f"https://www.instagram.com/p/{post.shortcode}/"
        is_video = post.is_video
        print(f"  Post {i}: {url} | {post.date_utc} | video={is_video} | {cap}")
        if i >= 2:
            break
    print("SUCCESS")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
    import traceback; traceback.print_exc()
