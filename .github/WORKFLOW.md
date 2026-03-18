# Scraping Workflow Strategy

1. **Discovery:** Identify the news URL and check if it's SSR (Server Side) or CSR (Client Side).
2. **Initialization:** Launch `undetected-chromedriver` with specific arguments (`--incognito`, `--disable-gpu`).
3. **Navigation:** Navigate to the "Seguridad" or "Cali" section of the portal.
4. **Parsing:** - Use Selenium to get the full Page Source after JS execution.
   - Pass the source to BeautifulSoup for precision extraction.
5. **Validation:** Check if the data extracted matches the Cali security context (Keywords: "homicidio", "hurto", "percepción", "seguridad", "policía").
6. **Storage:** Save to a temporary buffer and then append to the master dataset.
