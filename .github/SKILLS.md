# Specialized Scraping Skills

## 1. Advanced Stealth Scraping

- **Bypassing Bot Detection:** Use `undetected-chromedriver` to evade TLS fingerprinting.
- **Human Mimicry:** Implement random delays (`time.sleep` with Gaussian distribution) and variable user-agents.
- **Dynamic Interaction:** Handle infinite scrolls, "Read More" buttons, and Shadow DOMs using Selenium Expected Conditions (EC).

## 2. Content Extraction (NLP Ready)

- **Targeting:** Extract Title, Date, Author, Content, and Neighborhood (Barrio) mentioned.
- **Cleaning:** Remove boilerplate (ads, scripts, navbars) using BeautifulSoup's `.decompose()`.
- **Normalization:** Format dates to ISO-8601 and clean text for Spanish NLP (remove stop words, lemmatization prep).

## 3. Resilience Logic

- **Retries:** Implement Exponential Backoff for failed requests.
- **Proxy Rotation:** Structure code to easily integrate proxy lists if needed.
