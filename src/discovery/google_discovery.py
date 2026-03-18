from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import parse_qs, urlparse, urlunparse

from bs4 import BeautifulSoup

log = logging.getLogger("scraper")


def _dedupe_keep_order(values: list[str]) -> list[str]:
    return list(dict.fromkeys([v.strip().lower() for v in values if v and v.strip()]))


def _is_probable_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.netloc:
        return False

    path = parsed.path.lower().strip()
    if not path or path == "/":
        return False

    blocked_exact = {"/cali", "/cali/", "/judicial", "/judicial/", "/colombia", "/colombia/"}
    if path in blocked_exact:
        return False

    blocked_fragments = ["/tag/", "/autor/", "/podcast/", "/video/", "/newsletter/", "/suscrib"]
    if any(fragment in path for fragment in blocked_fragments):
        return False

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return False

    slug = parts[-1]
    if slug in {"index", "home", "noticias", "news"}:
        return False

    return ("-" in slug) or slug.endswith(".html") or len(slug) >= 18


def _build_security_keyword_bank(custom_keywords: list[str] | None) -> list[str]:
    base = [
        "seguridad",
        "judicial",
        "justicia",
        "bandas criminales",
        "terrorismo",
        "policia",
        "homicidio",
        "homicidios",
        "hurto",
        "hurtos",
        "abuso",
        "corrupcion",
        "corrupción",
        "fiscalia",
        "fiscalía",
        "captura",
        "capturados",
        "allanamiento",
        "extorsion",
        "extorsión",
        "sicariato",
        "microtrafico",
        "microtráfico",
        "narcotrafico",
        "narcotráfico",
        "delincuencia",
        "criminalidad",
        "violencia",
        "orden publico",
        "orden público",
        "seguridad ciudadana",
        "inseguridad",
        "robo",
        "atraco",
        "homicida",
        "control territorial",
        "ollas de microtráfico",
        'olla'
    ]
    if custom_keywords:
        base.extend(custom_keywords)
    return _dedupe_keep_order(base)


def _extract_google_result_links(
    html: str,
    allowed_domain: str,
    *,
    enforce_security_focus: bool,
    security_terms: list[str],
) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []

    for anchor in soup.select("a[href^='/url?q=']"):
        href = anchor.get("href") or ""
        query = parse_qs(urlparse(href).query)
        url = (query.get("q") or [""])[0]
        if not url:
            continue

        parsed = urlparse(url)
        if allowed_domain not in parsed.netloc.lower():
            continue

        cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        if not _is_probable_article_url(cleaned):
            continue

        # Do not over-filter here: structured query already enforces topical criteria.
        # Extra snippet-based filters may drop valid links and reduce recall.

        found.append(cleaned)

    return list(dict.fromkeys(found))


def _build_structured_queries(
    source: dict,
    *,
    enforce_security_focus: bool,
    security_terms: list[str],
) -> list[str]:
    source_queries: list[str] = source.get("google_queries") or []

    if not enforce_security_focus:
        return _dedupe_keep_order(source_queries + ["noticias", "actualidad", "cali"])

    geo_terms = ["cali", "santiago de cali", "valle del cauca"]
    justice_context = [
        "noticia",
        "caso",
        "investigacion",
        "investigación",
        "captura",
        "operativo",
        "denuncia",
        "fiscalia",
        "fiscalía",
        "juez",
        "tribunal",
    ]

    variants: list[str] = []
    variants.extend(source_queries)
    variants.extend(security_terms)

    for term in security_terms:
        for geo in geo_terms:
            variants.append(f"{term} {geo}")
            for ctx in justice_context:
                variants.append(f"{term} {geo} {ctx}")

    return _dedupe_keep_order(variants)


def discover_articles_with_google(
    source: dict,
    fetch_html,
    start_date: datetime | None,
    end_date: datetime | None,
    max_results: int,
    security_keywords: list[str] | None = None,
    max_queries_per_source: int = 220,
    max_queries_per_run: int = 30,
    parallel_queries: int = 6,
    enforce_security_focus: bool = True,
    pages_per_query: int = 1,
    results_per_page: int = 20,
) -> list[str]:
    """Discover article URLs from Google.

    Unlimited mode:
    - max_results <= 0: no internal cap on collected URLs
    - max_queries_per_source <= 0: use full generated query bank
    - max_queries_per_run <= 0: run all selected queries
    - pages_per_query <= 0: keep paginating until no results (bounded by safety cap)
    """
    base_domain = urlparse(source["base_url"]).netloc.lower().replace("www.", "")
    security_terms = _build_security_keyword_bank(security_keywords)
    queries = _build_structured_queries(
        source,
        enforce_security_focus=enforce_security_focus,
        security_terms=security_terms,
    )

    if max_queries_per_source > 0:
        queries = queries[:max_queries_per_source]

    run_cap = len(queries) if max_queries_per_run <= 0 else max(1, min(max_queries_per_run, len(queries)))
    planned_terms = queries[:run_cap]

    log.info("Google discovery: %d queries generadas, %d seleccionadas para ejecución", len(queries), run_cap)

    per_page = max(10, min(results_per_page, 100))
    max_pages_safety = 20
    total_pages = max_pages_safety if pages_per_query <= 0 else max(1, min(pages_per_query, max_pages_safety))

    date_filter = ""
    if start_date and end_date:
        date_filter = f" after:{start_date.strftime('%Y-%m-%d')} before:{end_date.strftime('%Y-%m-%d')}"

    urls: list[str] = []
    max_urls = max_results if max_results > 0 else 10**9

    def _run_query(term: str) -> list[str]:
        collected: list[str] = []
        q = f"site:{base_domain} cali {term}{date_filter}"
        log.debug("Google query: %s", q)

        def _google_url(start_offset: int) -> str:
            return (
                "https://www.google.com/search"
                f"?q={q.replace(' ', '+')}&hl=es&gl=co&pws=0&safe=off&filter=0"
                f"&num={per_page}&start={start_offset}"
            )

        # Unlimited pagination mode: advance until multiple consecutive pages add no new links.
        if pages_per_query <= 0:
            consecutive_no_new = 0
            for page in range(total_pages):
                if page > 0:
                    time.sleep(1.5)
                start_offset = page * per_page
                try:
                    html = fetch_html(_google_url(start_offset))
                except Exception as exc:
                    log.debug("Google page %d falló para '%s': %s", page, term, exc)
                    consecutive_no_new += 1
                    if consecutive_no_new >= 3:
                        break
                    continue

                links = _extract_google_result_links(
                    html,
                    base_domain,
                    enforce_security_focus=enforce_security_focus,
                    security_terms=security_terms,
                )
                new_added = 0
                for link in links:
                    if link not in collected:
                        collected.append(link)
                        new_added += 1

                if new_added == 0:
                    consecutive_no_new += 1
                else:
                    consecutive_no_new = 0

                if consecutive_no_new >= 3:
                    break
            return collected

        # Fixed pagination mode: fetch page batches in parallel for speed.
        page_workers = max(1, min(8, workers))
        offsets = [page * per_page for page in range(total_pages)]
        batch_size = max(1, page_workers * 2)
        for i in range(0, len(offsets), batch_size):
            batch = offsets[i : i + batch_size]
            with ThreadPoolExecutor(max_workers=page_workers) as page_pool:
                future_to_offset = {
                    page_pool.submit(fetch_html, _google_url(offset)): offset for offset in batch
                }
                for future in as_completed(future_to_offset):
                    try:
                        html = future.result()
                    except Exception:
                        continue
                    links = _extract_google_result_links(
                        html,
                        base_domain,
                        enforce_security_focus=enforce_security_focus,
                        security_terms=security_terms,
                    )
                    for link in links:
                        if link not in collected:
                            collected.append(link)

        return collected

    workers = max(1, min(parallel_queries, len(planned_terms)))
    log.info("Google discovery: ejecutando %d queries con %d workers, %d páginas/query", len(planned_terms), workers, total_pages)
    if workers == 1:
        for idx, term in enumerate(planned_terms, 1):
            if len(urls) >= max_urls:
                break
            log.info("Google query %d/%d: '%s' (URLs acumuladas: %d)", idx, len(planned_terms), term[:50], len(urls))
            for link in _run_query(term):
                if link not in urls:
                    urls.append(link)
                    if len(urls) >= max_urls:
                        break
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_query, term): term for term in planned_terms}
            done_count = 0
            for future in as_completed(futures):
                done_count += 1
                term = futures[future]
                if len(urls) >= max_urls:
                    break
                try:
                    links = future.result()
                except Exception as exc:
                    log.warning("Google query falló '%s': %s", term[:50], exc)
                    continue
                new = 0
                for link in links:
                    if link not in urls:
                        urls.append(link)
                        new += 1
                        if len(urls) >= max_urls:
                            break
                if done_count % 5 == 0 or new > 0:
                    log.info("Google progress: %d/%d queries completadas, %d URLs únicas", done_count, len(planned_terms), len(urls))

    log.info("Google discovery finalizado: %d URLs encontradas", len(urls))
    return urls[:max_urls]
