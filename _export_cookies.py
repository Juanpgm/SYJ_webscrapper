"""
Abre un navegador, espera a que inicies sesion en Instagram,
y exporta las cookies a config/instagram_cookies.txt
"""
import time
from pathlib import Path

import undetected_chromedriver as uc

COOKIE_FILE = Path("config/instagram_cookies.txt")


def main():
    print("Abriendo navegador...")
    options = uc.ChromeOptions()
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    driver = uc.Chrome(options=options, headless=False)

    driver.get("https://www.instagram.com/accounts/login/")
    print()
    print("=" * 60)
    print("  INICIA SESION EN INSTAGRAM EN LA VENTANA DEL NAVEGADOR")
    print("  Cuando estes logueado, vuelve aqui y espera.")
    print("=" * 60)
    print()

    # Wait until logged in
    for _ in range(300):  # max 10 min
        time.sleep(2)
        try:
            url = driver.current_url
            if "instagram.com" in url and "/accounts/login" not in url and "/challenge" not in url:
                cookies = driver.get_cookies()
                session_ids = [c for c in cookies if c["name"] in ("sessionid", "ds_user_id")]
                if session_ids:
                    print("Login detectado! Exportando cookies...")
                    break
        except Exception:
            pass
    else:
        print("Timeout esperando login. Abortando.")
        driver.quit()
        return

    # Export in Netscape cookies.txt format
    cookies = driver.get_cookies()
    lines = ["# Netscape HTTP Cookie File", "# https://curl.se/docs/http-cookies.html", ""]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expiry = str(int(c.get("expiry", 0)))
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append("\t".join([domain, flag, path, secure, expiry, name, value]))

    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Cookies exportadas a: {COOKIE_FILE}")
    print(f"Total cookies: {len(cookies)}")

    ig_names = [c["name"] for c in cookies if "instagram" in c.get("domain", "")]
    print(f"Instagram cookies: {ig_names}")

    driver.quit()
    print("Listo! Ya puedes correr el scraper.")


if __name__ == "__main__":
    main()
