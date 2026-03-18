from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from src.social.base_connector import BaseSocialConnector
from src.social.youtube_transcript import YouTubeTranscriptService, extract_video_id
from src.utils.dates import normalize_to_ddmmyyyy, now_ddmmyyyy


class YouTubeConnector(BaseSocialConnector):
    def fetch_items(
        self,
        *,
        start_date: datetime | None,
        end_date: datetime | None,
        keywords: list[str] | None,
    ) -> list[dict]:
        if self.browser_fetch_html is None:
            return []

        queries = list(self.source.get("search_queries") or keywords or [])
        if not queries:
            return []

        max_videos_per_query = int(self.source.get("max_videos_per_query", 2))
        max_comments_per_video = int(self.source.get("max_comments_per_video", 8))
        transcript_service = YouTubeTranscriptService(
            languages=list(self.source.get("transcript_languages") or ["es", "es-419", "en"]),
            enable_audio_fallback=bool(self.source.get("audio_transcription_enabled", True)),
            whisper_model=str(self.source.get("whisper_model", "tiny")),
            whisper_device=str(self.source.get("whisper_device", "auto")),
            whisper_compute_type=str(self.source.get("whisper_compute_type", "int8")),
        )
        collected: list[dict] = []
        seen_urls: set[str] = set()

        for query in queries:
            search_url = f"https://www.youtube.com/results?search_query={quote(query)}"
            try:
                search_html = self.browser_fetch_html(search_url)
            except Exception:
                continue

            soup = BeautifulSoup(search_html, "lxml")
            video_urls: list[str] = []
            for node in soup.select("a#video-title, a[href^='/watch']"):
                href = node.get("href")
                if not href or "/watch" not in href:
                    continue
                video_url = urljoin("https://www.youtube.com", href.split("&")[0])
                if video_url not in video_urls:
                    video_urls.append(video_url)
                if len(video_urls) >= max_videos_per_query:
                    break

            for video_url in video_urls:
                if video_url in seen_urls:
                    continue
                try:
                    html = self.browser_fetch_html(video_url)
                except Exception:
                    continue

                item_soup = BeautifulSoup(html, "lxml")
                title = (
                    (item_soup.select_one("meta[name='title']") or {}).get("content")
                    if item_soup.select_one("meta[name='title']")
                    else ""
                ) or " ".join(item_soup.title.get_text(" ", strip=True).split()) if item_soup.title else ""
                description = (
                    (item_soup.select_one("meta[name='description']") or {}).get("content")
                    if item_soup.select_one("meta[name='description']")
                    else ""
                )
                channel = " ".join(item_soup.select_one("link[itemprop='name']").get("content", "").split()) if item_soup.select_one("link[itemprop='name']") else None
                published = (
                    (item_soup.select_one("meta[itemprop='datePublished']") or {}).get("content")
                    if item_soup.select_one("meta[itemprop='datePublished']")
                    else None
                )
                transcript = transcript_service.fetch(video_url)
                transcript_text = str(transcript.get("text") or "").strip()
                transcript_source = transcript.get("source")

                comments: list[dict] = []
                for thread in item_soup.select("ytd-comment-thread-renderer, ytd-comment-renderer"):
                    text_node = thread.select_one("yt-formatted-string#content-text, div#content-text")
                    if text_node is None:
                        continue
                    text = " ".join(text_node.get_text(" ", strip=True).split())
                    if not text:
                        continue

                    user_node = thread.select_one("#author-text span, a#author-text span")
                    date_node = thread.select_one(
                        "span.published-time-text a, yt-formatted-string.published-time-text a, a[href*='lc=']"
                    )
                    comments.append(
                        {
                            "fecha_hora": " ".join(date_node.get_text(" ", strip=True).split()) if date_node else None,
                            "usuario": " ".join(user_node.get_text(" ", strip=True).split()) if user_node else None,
                            "texto": text,
                        }
                    )
                    if len(comments) >= max_comments_per_video:
                        break

                if not comments:
                    for node in item_soup.select("yt-formatted-string#content-text, div#content-text"):
                        text = " ".join(node.get_text(" ", strip=True).split())
                        if not text:
                            continue
                        comments.append({"fecha_hora": None, "usuario": None, "texto": text})
                        if len(comments) >= max_comments_per_video:
                            break

                comments_text = [item["texto"] for item in comments if item.get("texto")]

                raw_sections: list[str] = []
                if title:
                    raw_sections.append(f"Titulo: {title}")
                if description:
                    raw_sections.append(f"Descripcion: {description}")
                if transcript_text:
                    label = f"Transcripcion ({transcript_source})" if transcript_source else "Transcripcion"
                    raw_sections.append(f"{label}: {transcript_text}")
                if comments_text:
                    raw_sections.append("Comentarios: " + " || ".join(comments_text))

                raw_text = "\n\n".join(section for section in raw_sections if section).strip() or title
                if not raw_text:
                    continue

                seen_urls.add(video_url)
                best_snippet = transcript_text[:280] if transcript_text else comments_text[0][:280] if comments_text else description[:280] if description else title[:280]
                collected.append(
                    {
                        "fecha_obtencion": now_ddmmyyyy(),
                        "fecha_publicacion": normalize_to_ddmmyyyy(published),
                        "fuente": self.source.get("name", "YouTube"),
                        "raw_text": raw_text,
                        "snippet_text": best_snippet,
                        "title": title,
                        "url_noticia": video_url,
                        "source_type": "social",
                        "platform": "youtube",
                        "content_kind": "video_transcript" if transcript_text else "video_comments",
                        "author_name": channel,
                        "canonical_id": extract_video_id(video_url),
                        "description_text": description or None,
                        "transcript_text": transcript_text or None,
                        "transcript_source": transcript_source,
                        "comments_text": comments_text,
                        "comments": comments,
                        "n_comments": len(comments),
                    }
                )

        return collected
