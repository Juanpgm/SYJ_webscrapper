"""Quick test: scrape ONE post to verify comment extraction + reel_url."""
import json
import time
from src.social.instagram_connector import (
    _scrape_post_page,
    _extract_post_links_from_profile,
    _load_cookies_into_driver,
    InstagramConnector,
)

print("=== Creando driver Selenium ===")
driver = InstagramConnector._build_ig_driver()
if not driver:
    print("ERROR: no se pudo crear driver")
    exit(1)

try:
    # Load cookies
    print("=== Cargando cookies ===")
    driver.get("https://www.instagram.com/")
    time.sleep(1.5)
    _load_cookies_into_driver(driver, "config/instagram_cookies.txt")
    driver.refresh()
    time.sleep(2.0)

    logged = "sessionid" in {c["name"] for c in driver.get_cookies()}
    print(f"Sesion: {'activa' if logged else 'NO detectada'}")

    # First get a valid recent post URL from the profile
    print("\n=== Obteniendo posts recientes de zonacnoticiasoficial ===")
    links = _extract_post_links_from_profile(
        driver, "https://www.instagram.com/zonacnoticiasoficial/", max_posts=3
    )
    print(f"Posts encontrados: {len(links)}")
    for lnk in links:
        print(f"  -> {lnk}")

    if not links:
        print("ERROR: no se encontraron posts")
        exit(1)

    # Prefer reel (more comments) if available
    TEST_URL = next((l for l in links if "/reel/" in l), links[0])
    print(f"\n=== Scrapeando post: {TEST_URL} ===")
    result = _scrape_post_page(driver, TEST_URL, max_comments=20)

    # Dump a snippet of page source for DOM inspection
    try:
        src = driver.page_source
        with open("_debug_page_source.html", "w", encoding="utf-8") as f:
            f.write(src)
        print(f"[DEBUG] Page source guardado en _debug_page_source.html ({len(src)} chars)")
    except Exception as e:
        print(f"[DEBUG] No se pudo guardar page source: {e}")

    if not result:
        print("ERROR: sin resultados")
    else:
        print(f"\n--- RESULTADO ---")
        print(f"post_type:  {result.get('post_type')}")
        print(f"author:     {result.get('author')}")
        print(f"caption:    {(result.get('caption') or '')[:200]}...")
        print(f"video_url:  {('SI' if result.get('video_url') else 'NO')}")
        print(f"is_video:   {result.get('is_video')}")
        print(f"published:  {result.get('published')}")
        comments = result.get("comments", [])
        print(f"\n--- COMENTARIOS ({len(comments)}) ---")
        for i, c in enumerate(comments, 1):
            usuario = c.get("usuario") or "???"
            texto = (c.get("texto") or "")[:120]
            print(f"  {i}. @{usuario}: {texto}")

        print(f"\n--- JSON completo ---")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str)[:3000])

finally:
    driver.quit()
    print("\n=== Driver cerrado ===")
