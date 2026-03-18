from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup

from src.social.base_connector import BaseSocialConnector
from src.social.media_transcriber import MediaTranscriber
from src.utils.dates import normalize_to_ddmmyyyy, now_ddmmyyyy


def _normalize_instagram_url(href: str) -> str | None:
    if not href:
        return None
    if href.startswith("/"):
        href = urljoin("https://www.instagram.com", href)
    if "instagram.com" not in href:
        return None
    parsed = urlparse(href)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    if parts[0] not in {"p", "reel", "tv"}:
        return None
    return f"https://www.instagram.com/{parts[0]}/{parts[1]}/"


def _extract_post_id(post_url: str) -> str | None:
    parsed = urlparse(post_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"p", "reel", "tv"}:
        return parts[1]
    return None


class InstagramConnector(BaseSocialConnector):
    def fetch_items(
        self,
        *,
        start_date: datetime | None,
        end_date: datetime | None,
        keywords: list[str] | None,
    ) -> list[dict]:
        if self.browser_fetch_html is None:
            return []

        profile_urls = list(self.source.get("profile_urls") or [])
        direct_post_urls = list(self.source.get("post_urls") or [])
        hashtags = list(self.source.get("hashtags") or [])
        max_posts_per_profile = int(self.source.get("max_posts_per_profile", 8))
        max_comments_per_post = int(self.source.get("max_comments_per_post", 12))
        transcribe_videos = bool(self.source.get("transcribe_videos", True))

        whisper_model = str(self.source.get("whisper_model", "tiny"))
        whisper_device = str(self.source.get("whisper_device", "auto"))
        whisper_compute_type = str(self.source.get("whisper_compute_type", "int8"))
        transcriber = MediaTranscriber(
            whisper_model=whisper_model,
            whisper_device=whisper_device,
            whisper_compute_type=whisper_compute_type,
        )

        listing_urls = list(profile_urls)
        for hashtag in hashtags:
            clean_tag = str(hashtag).strip().lstrip("#")
            if clean_tag:
                listing_urls.append(f"https://www.instagram.com/explore/tags/{quote(clean_tag)}/")

        seen_posts: set[str] = set()
        collected: list[dict] = []

        for raw_url in direct_post_urls:
            post_url = _normalize_instagram_url(str(raw_url))
            if not post_url or post_url in seen_posts:
                continue
            item = self._fetch_single_post(
                post_url=post_url,
                max_comments=max_comments_per_post,
                transcribe_videos=transcribe_videos,
                transcriber=transcriber,
            )
            if item is None:
                continue
            seen_posts.add(post_url)
            collected.append(item)

        for listing_url in listing_urls:
            try:
                listing_html = self.browser_fetch_html(listing_url)
            except Exception:
                continue

            soup = BeautifulSoup(listing_html, "lxml")
            post_urls: list[str] = []
            for link in soup.select("a[href]"):
                post_url = _normalize_instagram_url(str(link.get("href") or ""))
                if not post_url or post_url in post_urls:
                    continue
                post_urls.append(post_url)
                if len(post_urls) >= max_posts_per_profile:
                    break

            if len(post_urls) < max_posts_per_profile:
                found = re.findall(r'/(?:p|reel|tv)/[A-Za-z0-9_-]+/?', listing_html)
                for match in found:
                    post_url = _normalize_instagram_url(match)
                    if not post_url or post_url in post_urls:
                        continue
                    post_urls.append(post_url)
                    if len(post_urls) >= max_posts_per_profile:
                        break

            for post_url in post_urls:
                if post_url in seen_posts:
                    continue
                item = self._fetch_single_post(
                    post_url=post_url,
                    max_comments=max_comments_per_post,
                    transcribe_videos=transcribe_videos,
                    transcriber=transcriber,
                )
                if item is None:
                    continue
                seen_posts.add(post_url)
                collected.append(item)

        return collected

    def _fetch_single_post(
        self,
        *,
        post_url: str,
        max_comments: int,
        transcribe_videos: bool,
        transcriber: MediaTranscriber,
    ) -> dict | None:
        try:
            html = self.browser_fetch_html(post_url) if self.browser_fetch_html is not None else self.fetch_html(post_url)
        except Exception:
            return None

        soup = BeautifulSoup(html, "lxml")
        metadata = self._extract_ld_json_metadata(soup)
        caption = metadata.get("caption") or self._extract_meta_description(soup)
        author = metadata.get("author")
        published = metadata.get("published")

        comments = self._extract_comments_from_dom(soup, max_comments)
        comments_text = [comment["texto"] for comment in comments if comment.get("texto")]
        video_url = self._extract_video_url(html)

        transcript_text = ""
        transcript_source = None
        if transcribe_videos and video_url:
            transcript_text = transcriber.transcribe_media_url(video_url, language="es")
            if transcript_text:
                transcript_source = "whisper"

        if not any([caption, comments_text, transcript_text]):
            return None

        content_kind = "reel" if "/reel/" in post_url else "post"
        if video_url and content_kind == "post":
            content_kind = "video_post"

        title = (caption or transcript_text or (comments_text[0] if comments_text else "Instagram post")).strip()

        sections: list[str] = []
        if caption:
            sections.append(f"Descripcion: {caption}")
        if transcript_text:
            sections.append(f"Transcripcion ({transcript_source}): {transcript_text}")
        if comments_text:
            sections.append("Comentarios: " + " || ".join(comments_text))

        raw_text = "\n\n".join(section for section in sections if section).strip() or title
        if not raw_text:
            return None

        return {
            "fecha_obtencion": now_ddmmyyyy(),
            "fecha_publicacion": normalize_to_ddmmyyyy(published),
            "fuente": self.source.get("name", "Instagram Publico"),
            "raw_text": raw_text,
            "snippet_text": (transcript_text[:280] if transcript_text else (caption or "")[:280] if caption else title[:280]),
            "title": title,
            "url_noticia": post_url,
            "source_type": "social",
            "platform": "instagram",
            "content_kind": content_kind,
            "author_name": author,
            "canonical_id": _extract_post_id(post_url),
            "description_text": caption or None,
            "transcript_text": transcript_text or None,
            "transcript_source": transcript_source,
            "comments_text": comments_text,
            "comments": comments,
            "n_comments": len(comments),
        }

    def _extract_ld_json_metadata(self, soup: BeautifulSoup) -> dict[str, str | None]:
        values = {"caption": None, "author": None, "published": None}
        for node in soup.select("script[type='application/ld+json']"):
            raw = (node.string or node.get_text("", strip=True) or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if not isinstance(item, dict):
                    continue
                article_body = item.get("articleBody") or item.get("caption") or item.get("description")
                if isinstance(article_body, str) and not values["caption"]:
                    values["caption"] = " ".join(article_body.split())

                author = item.get("author")
                if isinstance(author, dict):
                    author_name = author.get("alternateName") or author.get("name")
                else:
                    author_name = author
                if isinstance(author_name, str) and author_name.strip() and not values["author"]:
                    values["author"] = author_name.strip()

                published = item.get("uploadDate") or item.get("datePublished")
                if isinstance(published, str) and published.strip() and not values["published"]:
                    values["published"] = published.strip()

        return values

    @staticmethod
    def _extract_meta_description(soup: BeautifulSoup) -> str:
        node = soup.select_one("meta[property='og:description'], meta[name='description']")
        if node is None:
            return ""
        content = str(node.get("content") or "").strip()
        if not content:
            return ""
        return " ".join(content.split())

    @staticmethod
    def _extract_video_url(html: str) -> str | None:
        patterns = [
            r'"video_url":"(https:[^"\\]+(?:\\u0026[^"\\]+)*)"',
            r'"contentUrl":"(https:[^"\\]+(?:\\u0026[^"\\]+)*)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if not match:
                continue
            value = match.group(1).replace("\\/", "/").replace("\\u0026", "&")
            return value
        return None

    @staticmethod
    def _extract_comments_from_dom(soup: BeautifulSoup, max_comments: int) -> list[dict]:
        comments: list[dict] = []
        seen: set[str] = set()
        for node in soup.select("article ul ul li, article div[role='button'] + ul li, article li"):
            text_node = node.select_one("span")
            if text_node is None:
                continue
            text = " ".join(text_node.get_text(" ", strip=True).split())
            if len(text) < 3:
                continue

            user_node = node.select_one("h3, a[href^='/']")
            time_node = node.select_one("time")
            username = " ".join(user_node.get_text(" ", strip=True).split()) if user_node is not None else None
            fecha_hora = str(time_node.get("datetime") or "").strip() or None if time_node is not None else None

            dedupe_key = f"{username or ''}|{text}".lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            comments.append({"fecha_hora": fecha_hora, "usuario": username, "texto": text})
            if len(comments) >= max_comments:
                break
        return comments