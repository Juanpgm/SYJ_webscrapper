from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from src.social.base_connector import BaseSocialConnector
from src.utils.dates import normalize_to_ddmmyyyy, now_ddmmyyyy


class NitterConnector(BaseSocialConnector):
    def _fetch_replies(self, status_url: str, limit: int) -> list[dict]:
        html = ""
        try:
            html = self.fetch_html(status_url)
        except Exception:
            if self.browser_fetch_html is not None:
                try:
                    html = self.browser_fetch_html(status_url)
                except Exception:
                    html = ""
        if not html:
            return []

        soup = BeautifulSoup(html, "lxml")
        replies: list[dict] = []
        for node in soup.select("div.replies div.timeline-item, div.timeline-item.reply"):
            text_node = node.select_one("div.tweet-content")
            text = " ".join(text_node.get_text(" ", strip=True).split()) if text_node else ""
            if not text:
                continue
            user_node = node.select_one("a.fullname, span.fullname, a.username, span.username")
            date_node = node.select_one("a.tweet-date")
            replies.append(
                {
                    "fecha_hora": str(date_node.get("title") or "").strip() or None,
                    "usuario": " ".join(user_node.get_text(" ", strip=True).split()) if user_node else None,
                    "texto": text,
                }
            )
            if len(replies) >= limit:
                break
        return replies

    def fetch_items(
        self,
        *,
        start_date: datetime | None,
        end_date: datetime | None,
        keywords: list[str] | None,
        existing_urls: set[str] | None = None,
    ) -> list[dict]:
        queries = list(self.source.get("search_queries") or keywords or [])
        if not queries:
            return []

        instances = self.source.get("instances") or ["https://nitter.net"]
        max_posts = int(self.source.get("max_posts", 20))
        max_comments_per_post = int(self.source.get("max_comments_per_post", 5))
        prefer_browser = bool(self.source.get("prefer_browser", False))
        collected: list[dict] = []
        seen_urls: set[str] = set()

        for query in queries:
            for instance in instances:
                search_url = f"{instance.rstrip('/')}/search?f=tweets&q={quote(query)}"
                html = ""
                try:
                    if prefer_browser and self.browser_fetch_html is not None:
                        html = self.browser_fetch_html(search_url)
                    else:
                        html = self.fetch_html(search_url)
                except Exception:
                    if self.browser_fetch_html is not None and not prefer_browser:
                        try:
                            html = self.browser_fetch_html(search_url)
                        except Exception:
                            html = ""
                if not html:
                    continue

                soup = BeautifulSoup(html, "lxml")
                candidates = soup.select("div.timeline-item, article, div.main-tweet")
                for item in candidates:
                    text_node = item.select_one("div.tweet-content, div.main-tweet div.tweet-content, div[lang]")
                    text = " ".join(text_node.get_text(" ", strip=True).split()) if text_node else ""
                    if not text:
                        continue

                    date_node = item.select_one("a.tweet-date, a[href*='/status/']")
                    href = date_node.get("href") if date_node else None
                    url_noticia = urljoin(instance, href) if href else None
                    if not url_noticia or url_noticia in seen_urls:
                        continue

                    date_hint = date_node.get("title") if date_node else None
                    author_name = " ".join(item.select_one("a.fullname, span.fullname").get_text(" ", strip=True).split()) if item.select_one("a.fullname, span.fullname") else None
                    author_handle = item.select_one("a.username, span.username")
                    author_handle_text = author_handle.get_text(" ", strip=True) if author_handle else None
                    comments = self._fetch_replies(url_noticia, max_comments_per_post)

                    seen_urls.add(url_noticia)
                    collected.append(
                        {
                            "fecha_obtencion": now_ddmmyyyy(),
                            "fecha_publicacion": normalize_to_ddmmyyyy(date_hint),
                            "fuente": self.source.get("name", "Nitter"),
                            "raw_text": text,
                            "snippet_text": text[:280],
                            "title": text[:160],
                            "url_noticia": url_noticia,
                            "source_type": "social",
                            "platform": "x",
                            "content_kind": "post",
                            "author_name": author_name,
                            "author_handle": author_handle_text,
                            "canonical_id": url_noticia.rstrip("/").split("/")[-1],
                            "comments": comments,
                            "comments_text": [reply["texto"] for reply in comments if reply.get("texto")],
                            "n_comments": len(comments),
                        }
                    )
                    if len(collected) >= max_posts:
                        return collected

        return collected
