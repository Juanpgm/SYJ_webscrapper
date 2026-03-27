from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.social.base_connector import BaseSocialConnector
from src.utils.dates import normalize_to_ddmmyyyy, now_ddmmyyyy


class FacebookConnector(BaseSocialConnector):
    def fetch_items(
        self,
        *,
        start_date: datetime | None,
        end_date: datetime | None,
        keywords: list[str] | None,
        existing_urls: set[str] | None = None,
    ) -> list[dict]:
        page_urls = list(self.source.get("page_urls") or [])
        max_posts_per_page = int(self.source.get("max_posts_per_page", 8))
        if not page_urls:
            return []

        collected: list[dict] = []
        seen_urls: set[str] = set()

        for page_url in page_urls:
            try:
                if bool(self.source.get("prefer_browser", False)) and self.browser_fetch_html is not None:
                    html = self.browser_fetch_html(page_url)
                else:
                    html = self.fetch_html(page_url)
            except Exception:
                if self.browser_fetch_html is None:
                    continue
                try:
                    html = self.browser_fetch_html(page_url)
                except Exception:
                    continue

            soup = BeautifulSoup(html, "lxml")
            candidates = soup.select("article, div.story_body_container, div[data-ft], div[role='article']")
            for item in candidates:
                text_parts = [
                    " ".join(node.get_text(" ", strip=True).split())
                    for node in item.select("p, span[data-ad-preview='message'], div[data-ad-comet-preview='message']")
                ]
                text = " ".join(part for part in text_parts if part).strip()
                if len(text) < 30:
                    continue

                link_node = item.select_one("a[href*='story.php'], a[href*='/posts/'], a[href*='/videos/'], a[href*='fbid=']")
                href = link_node.get("href") if link_node else None
                url_noticia = urljoin(page_url, href) if href else page_url
                if url_noticia in seen_urls:
                    continue

                date_node = item.select_one("abbr")
                comments: list[dict] = []
                for comment_node in item.select(
                    "[class*='comment'], [aria-label*='comentario'], [aria-label*='comment'], ul[role='list'] li"
                ):
                    comment_text = " ".join(comment_node.get_text(" ", strip=True).split())
                    if len(comment_text) < 8:
                        continue
                    user_node = comment_node.select_one("strong, h3, a")
                    comment_date_node = comment_node.select_one("abbr, time")
                    comments.append(
                        {
                            "fecha_hora": " ".join(comment_date_node.get_text(" ", strip=True).split()) if comment_date_node else None,
                            "usuario": " ".join(user_node.get_text(" ", strip=True).split()) if user_node else None,
                            "texto": comment_text,
                        }
                    )
                    if len(comments) >= 10:
                        break

                seen_urls.add(url_noticia)
                collected.append(
                    {
                        "fecha_obtencion": now_ddmmyyyy(),
                        "fecha_publicacion": normalize_to_ddmmyyyy(date_node.get_text(" ", strip=True) if date_node else None),
                        "fuente": self.source.get("name", "Facebook Publico"),
                        "raw_text": text,
                        "snippet_text": text[:280],
                        "title": text[:160],
                        "url_noticia": url_noticia,
                        "source_type": "social",
                        "platform": "facebook",
                        "content_kind": "public_post",
                        "canonical_id": url_noticia.rstrip("/").split("/")[-1],
                        "comments": comments,
                        "comments_text": [reply["texto"] for reply in comments if reply.get("texto")],
                        "n_comments": len(comments),
                    }
                )
                if len(collected) >= max_posts_per_page:
                    break

        return collected
