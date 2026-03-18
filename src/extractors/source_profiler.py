from __future__ import annotations

from bs4 import BeautifulSoup


def _text_for_selector(html: str, selector: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    node = soup.select_one(selector)
    if not node:
        return ""
    if node.name == "meta":
        return (node.get("content") or "").strip()
    return " ".join(node.get_text(" ", strip=True).split())


def _score_selector(html_samples: list[str], selector: str, content_mode: bool = False) -> float:
    hits = 0
    total_len = 0
    for html in html_samples:
        text = _text_for_selector(html, selector)
        if text:
            hits += 1
            total_len += len(text)

    if hits == 0:
        return 0.0

    avg_len = total_len / hits
    score = (hits * 10.0) + avg_len
    if content_mode and avg_len < 400:
        score *= 0.5
    return score


def infer_best_selectors(source: dict, html_samples: list[str]) -> dict:
    if not html_samples:
        return source.get("selectors", {})

    base = source.get("selectors", {})
    title_candidates = list(dict.fromkeys((base.get("title_selectors") or []) + ["h1", "meta[property='og:title']"]))
    date_candidates = list(
        dict.fromkeys(
            (base.get("date_selectors") or [])
            + [
                "time[datetime]",
                "meta[property='article:published_time']",
                "meta[name='pubdate']",
            ]
        )
    )
    content_candidates = list(
        dict.fromkeys(
            (base.get("content_selectors") or [])
            + [
                "[itemprop='articleBody']",
                "article",
                "main article",
                "div[class*='article-body']",
                "div[class*='story']",
            ]
        )
    )
    snippet_candidates = list(
        dict.fromkeys(
            (base.get("snippet_selectors") or [])
            + ["meta[name='description']", "meta[property='og:description']", "p[class*='summary']"]
        )
    )

    best_title = max(title_candidates, key=lambda s: _score_selector(html_samples, s), default="h1")
    best_date = max(date_candidates, key=lambda s: _score_selector(html_samples, s), default="time")
    best_content = max(content_candidates, key=lambda s: _score_selector(html_samples, s, content_mode=True), default="article")
    best_snippet = max(snippet_candidates, key=lambda s: _score_selector(html_samples, s), default="meta[name='description']")

    return {
        "title_selectors": [best_title] + [s for s in title_candidates if s != best_title],
        "date_selectors": [best_date] + [s for s in date_candidates if s != best_date],
        "content_selectors": [best_content] + [s for s in content_candidates if s != best_content],
        "snippet_selectors": [best_snippet] + [s for s in snippet_candidates if s != best_snippet],
    }
