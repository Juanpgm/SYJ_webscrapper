# Technical Stack & Tools

## Extraction Layer

- **Selenium + Undetected-Chromedriver:** For JS-heavy news sites and anti-bot bypass.
- **BeautifulSoup4:** For fast parsing of the static HTML returned by Selenium.
- **Requests:** Only for lightweight APIs or static RSS feeds.

## Data Processing

- **Pandas:** For structured data storage (DataFrame) and CSV/JSON export.
- **Pydantic:** To validate the schema of the scraped news (ensure no null titles or empty dates).

## NLP & Analytics (Future-proof)

- **TextBlob / VADER (Spanish versions):** For initial sentiment analysis.
- **SpaCy (es_core_news_lg):** For Named Entity Recognition (NER) to identify locations in Cali.
