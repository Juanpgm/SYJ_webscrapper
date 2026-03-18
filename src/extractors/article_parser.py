from urllib.parse import urljoin, urlparse
import re
import json

from bs4 import BeautifulSoup

from src.utils.dates import normalize_to_ddmmyyyy, now_ddmmyyyy


def discover_article_urls(listing_html: str, base_url: str, selectors: list[str]) -> list[str]:
    soup = BeautifulSoup(listing_html, "lxml")
    urls: list[str] = []
    blocked_fragments = [
        "/tag/",
        "/autor/",
        "/opinion/",
        "/video/",
        "/podcast/",
        "/newsletter/",
        "/suscrib",
    ]
    blocked_exact_paths = {
        "/",
        "/cali",
        "/cali/",
        "/judicial",
        "/judicial/",
        "/colombia",
        "/colombia/",
    }
    for selector in selectors:
        for node in soup.select(selector):
            href = node.get("href")
            if not href:
                continue
            if href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            absolute = urljoin(base_url, href)
            if not absolute.startswith("http"):
                continue
            if any(fragment in absolute.lower().rstrip("/") for fragment in blocked_fragments):
                continue
            parsed = urlparse(absolute)
            if parsed.path in blocked_exact_paths:
                continue
            path_parts = [part for part in parsed.path.split("/") if part]
            if len(path_parts) < 2:
                continue
            last_segment = path_parts[-1].lower()
            # Heuristic: article slugs are usually descriptive; listing pages are short/category-like.
            if last_segment in {"cali", "judicial", "colombia", "valle", "mundo"}:
                continue
            if not ("-" in last_segment or "." in last_segment or len(last_segment) >= 18):
                continue
            urls.append(absolute)
    return list(dict.fromkeys(urls))


def extract_article_payload(article_html: str, source_name: str, url_noticia: str, selectors: dict | None) -> dict:
    selectors = selectors if isinstance(selectors, dict) else {}
    soup = BeautifulSoup(article_html, "lxml")

    def selector_list(key: str, fallback: list[str]) -> list[str]:
        value = selectors.get(key)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return fallback

    spam_markers = [
        "noticias destacadas",
        "descarga la app",
        "suscrib",
        "inicia sesion",
        "crea cuenta",
        "siguenos en",
        "copyright",
        "servicio al cliente",
        "terminos de uso",
        "aviso de privacidad",
        "politica de tratamiento",
        "publicidad",
        "boletin",
        "google discover",
        "registrate gratis",
        "contenido en colaboracion",
    ]

    noise_regexes = [
        r"siga a .*google discover",
        r"reg[ií]strate gratis",
        r"descarga la app",
        r"noticias destacadas",
        r"contenido recomendado",
        r"lea tambi[eé]n",
        r"ver m[aá]s",
        r"publicidad",
        r"copyright",
        r"servicio al cliente",
        r"t[eé]rminos de uso",
        r"pol[ií]tica de privacidad",
        r"bolet[ií]n",
        r"inicia sesi[oó]n",
        r"crea cuenta",
        r"compartir",
        r"s[ií]guenos en",
        r"redacci[oó]n el pa[ií]s",
        r"actualizado el",
        r"convierta a .*fuente de noticias",
        r"\bfoto\s*:",
        r"\|\s*foto\s*:",
        r"comunicadora social con experiencia",
        r"redacci[oó]n\s+blu\s+radio",
    ]

    def is_noise_text(text: str) -> bool:
        if not text:
            return True
        low = text.lower().strip()
        if len(low) < 3:
            return True
        if not re.search(r"[a-záéíóúñ]", low):
            return True
        if re.match(r"^[0-9]+\s*\.\s*", low):
            return True
        if low.startswith("http://") or low.startswith("https://"):
            return True
        if low.count("|") >= 2 and "foto" in low:
            return True
        return any(re.search(pattern, low) for pattern in noise_regexes)

    def sanitize_article_text(text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"https?://\S+", " ", text)
        cleaned = re.sub(r"\|\s*foto\s*:[^\.\n]*", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bfoto\s*:[^\.\n]*", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if any(marker in cleaned.lower() for marker in spam_markers):
            return ""
        if is_noise_text(cleaned):
            return ""
        return cleaned

    def clean_node_text(node) -> str:
        # Remove common non-article blocks before extracting text.
        for tag in node.select(
            "script,style,noscript,nav,header,footer,aside,form,button,svg,iframe,figure figcaption"
        ):
            tag.decompose()

        noise_keywords = [
            "menu",
            "nav",
            "header",
            "footer",
            "breadcrumb",
            "suscrib",
            "newsletter",
            "compart",
            "social",
            "publicidad",
            "ads",
            "banner",
            "related",
            "recomend",
            "cookies",
            "destacadas",
            "boletin",
        ]
        for candidate in node.find_all(True):
            if not hasattr(candidate, "attrs") or candidate.attrs is None:
                continue
            attrs_blob = " ".join(
                [
                    candidate.get("id") or "",
                    " ".join(candidate.get("class", [])),
                    candidate.get("role") or "",
                    candidate.get("aria-label") or "",
                ]
            ).lower()
            if any(key in attrs_blob for key in noise_keywords):
                candidate.decompose()

        blocks = node.select("p, li, h2, h3, h4, blockquote")
        candidates: list[str] = []
        for block in blocks:
            full_text = " ".join(block.get_text(" ", strip=True).split())
            if not full_text:
                continue

            # Drop blocks that are mostly link hubs (related links, promos, menus).
            anchors = block.find_all("a")
            anchor_text = " ".join(" ".join(a.get_text(" ", strip=True).split()) for a in anchors).strip()
            anchor_density = (len(anchor_text) / max(1, len(full_text))) if anchors else 0.0
            if len(anchors) >= 1 and anchor_density > 0.45:
                continue

            # Remove anchor nodes from the extracted text to avoid including link labels/URLs.
            block_clone = BeautifulSoup(str(block), "lxml")
            for anchor in block_clone.select("a"):
                anchor.decompose()
            full_text = " ".join(block_clone.get_text(" ", strip=True).split())
            if not full_text:
                continue

            text = sanitize_article_text(full_text)
            if not is_noise_text(text):
                candidates.append(text)

        # Remove only consecutive duplicates; preserve repeated mentions that are far apart.
        if candidates:
            unique_candidates: list[str] = []
            previous = ""
            for candidate in candidates:
                if candidate != previous:
                    unique_candidates.append(candidate)
                previous = candidate
            return " ".join(unique_candidates)

        text = " ".join(node.get_text(" ", strip=True).split())
        return sanitize_article_text(text)

    def _iter_json_candidates(value):
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from _iter_json_candidates(item)
        elif isinstance(value, list):
            for item in value:
                yield from _iter_json_candidates(item)

    def extract_text_from_structured_data() -> str:
        candidates: list[str] = []
        for script in soup.select("script[type='application/ld+json']"):
            raw = (script.string or script.get_text("", strip=True) or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            for item in _iter_json_candidates(payload):
                if not isinstance(item, dict):
                    continue
                article_body = item.get("articleBody")
                if not isinstance(article_body, str):
                    continue
                cleaned = sanitize_article_text(article_body)
                if cleaned:
                    candidates.append(cleaned)

        if not candidates:
            return ""
        return max(candidates, key=len)

    def extract_comments_from_structured_data() -> list[dict]:
        comments: list[dict] = []
        for script in soup.select("script[type='application/ld+json']"):
            raw = (script.string or script.get_text("", strip=True) or "").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            for item in _iter_json_candidates(payload):
                if not isinstance(item, dict):
                    continue

                raw_comments = item.get("comment")
                if isinstance(raw_comments, dict):
                    raw_comments = [raw_comments]
                if not isinstance(raw_comments, list):
                    continue

                for raw_comment in raw_comments:
                    if not isinstance(raw_comment, dict):
                        continue
                    text = sanitize_article_text(
                        str(
                            raw_comment.get("text")
                            or raw_comment.get("description")
                            or raw_comment.get("articleBody")
                            or ""
                        )
                    )
                    if len(text) < 5:
                        continue

                    author = raw_comment.get("author")
                    if isinstance(author, dict):
                        user = str(author.get("name") or "").strip() or None
                    else:
                        user = str(author or "").strip() or None

                    fecha_hora = (
                        str(raw_comment.get("datePublished") or raw_comment.get("dateCreated") or "").strip() or None
                    )
                    comments.append({"fecha_hora": fecha_hora, "usuario": user, "texto": text})

        return comments

    def extract_comments_from_html() -> list[dict]:
        container_selectors = selector_list("comment_container_selectors", ["[class*='comment']", "[id*='comment']"])
        text_selectors = selector_list("comment_text_selectors", ["p", "[class*='content']", "[class*='text']", "blockquote"])
        author_selectors = selector_list(
            "comment_author_selectors",
            ["[class*='author']", "[class*='user']", "[itemprop='author']", "a[rel='author']"],
        )
        date_selectors = selector_list("comment_date_selectors", ["time", "[datetime]", "[class*='date']", "[class*='time']"])
        max_comments = int(selectors.get("max_comments", 40))

        comments: list[dict] = []
        seen_nodes = set()
        for container_css in container_selectors:
            for node in soup.select(container_css):
                node_id = id(node)
                if node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)

                attrs = " ".join(
                    [
                        node.get("id") or "",
                        " ".join(node.get("class", [])),
                        node.get("aria-label") or "",
                    ]
                ).lower()
                if any(token in attrs for token in ("comment-form", "comment-box", "comment-input", "disabled-comments")):
                    continue

                extracted_text = ""
                for text_css in text_selectors:
                    text_node = node.select_one(text_css)
                    if text_node is not None:
                        extracted_text = sanitize_article_text(" ".join(text_node.get_text(" ", strip=True).split()))
                        if extracted_text:
                            break
                if not extracted_text:
                    extracted_text = sanitize_article_text(" ".join(node.get_text(" ", strip=True).split()))
                if len(extracted_text) < 12:
                    continue

                user_node = None
                for author_css in author_selectors:
                    user_node = node.select_one(author_css)
                    if user_node is not None:
                        break

                date_node = None
                for date_css in date_selectors:
                    date_node = node.select_one(date_css)
                    if date_node is not None:
                        break

                user = " ".join(user_node.get_text(" ", strip=True).split()) if user_node else None
                fecha_hora = None
                if date_node is not None:
                    fecha_hora = (
                        str(date_node.get("datetime") or date_node.get("content") or date_node.get_text(" ", strip=True)).strip()
                        or None
                    )

                comments.append({"fecha_hora": fecha_hora, "usuario": user, "texto": extracted_text})
                if len(comments) >= max_comments:
                    return comments

        return comments

    def extract_text_from_article_blocks() -> str:
        block_selectors = [
            ".paywall [data-index] p[data-type='text']",
            ".RichTextArticleBody .RichTextBody p",
            ".RichTextArticleBody-body p",
            "[itemprop='articleBody'] p",
            "article p",
            "main article p",
            "div[class*='article-body'] p",
            "section[class*='article-body'] p",
        ]

        blocks: list[str] = []
        seen: set[str] = set()
        for css in block_selectors:
            for node in soup.select(css):
                cloned = BeautifulSoup(str(node), "lxml")
                for anchor in cloned.select("a"):
                    anchor.decompose()
                text = sanitize_article_text(" ".join(cloned.get_text(" ", strip=True).split()))
                if not text:
                    continue
                if text in seen:
                    continue
                seen.add(text)
                blocks.append(text)

        return " ".join(blocks).strip()

    def pick_best_content_text() -> str:
        structured_text = extract_text_from_structured_data()
        if structured_text:
            return structured_text

        block_text = extract_text_from_article_blocks()
        if len(block_text) >= 300:
            return block_text

        candidate_selectors = selectors.get("content_selectors", []) + [
            "article",
            "main article",
            "[itemprop='articleBody']",
            "div[class*='article-body']",
            "section[class*='article-body']",
            "div[class*='story']",
        ]

        best_text = ""
        best_score = -1
        seen: set[str] = set()
        for css in candidate_selectors:
            if css in seen:
                continue
            seen.add(css)
            for node in soup.select(css):
                cloned = BeautifulSoup(str(node), "lxml")
                text = clean_node_text(cloned)
                if not text:
                    continue
                paragraph_like = text.count(". ") + text.count(": ")
                score = len(text) + (paragraph_like * 20)
                if score > best_score:
                    best_score = score
                    best_text = text

        if best_text:
            return best_text

        cloned = BeautifulSoup(str(soup), "lxml")
        return sanitize_article_text(clean_node_text(cloned))

    def first_text(candidates: list[str], default: str = "") -> str:
        for css in candidates:
            node = soup.select_one(css)
            if node:
                text = ""
                if node.name == "meta":
                    text = (node.get("content") or "").strip()
                else:
                    text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        return default

    def prune_with_title_context(content_text: str, title_text: str) -> str:
        if not content_text or not title_text:
            return content_text

        stopwords = {
            "para",
            "desde",
            "sobre",
            "entre",
            "hasta",
            "este",
            "esta",
            "estos",
            "estas",
            "del",
            "de",
            "la",
            "el",
            "los",
            "las",
            "con",
            "por",
            "una",
            "uno",
            "que",
            "como",
            "cali",
        }
        title_tokens = [
            t
            for t in re.findall(r"[a-záéíóúñ]+", title_text.lower())
            if len(t) >= 5 and t not in stopwords
        ]
        if not title_tokens:
            return content_text

        content_lower = content_text.lower()

        # High-confidence anchor: find first meaningful title bigram inside article body.
        bigrams: list[str] = []
        for idx in range(len(title_tokens) - 1):
            bigrams.append(f"{title_tokens[idx]} {title_tokens[idx + 1]}")

        best_pos = -1
        for bigram in bigrams:
            pos = content_lower.find(bigram)
            if pos == -1:
                continue
            if best_pos == -1 or pos < best_pos:
                best_pos = pos

        if best_pos > 80:
            trimmed = content_text[best_pos:].strip()
            if len(trimmed) > 120:
                return trimmed

        title_set = set(title_tokens)
        sentences = re.split(r"(?<=[\.!?])\s+", content_text)
        if len(sentences) < 4:
            return content_text

        start_idx = 0
        for idx, sentence in enumerate(sentences[:10]):
            words = set(re.findall(r"[a-záéíóúñ]+", sentence.lower()))
            overlap = len(words.intersection(title_set))
            if overlap >= 2 and len(sentence) >= 40:
                start_idx = idx
                break

        pruned = " ".join(sentences[start_idx:]).strip()
        return pruned or content_text

    title = first_text(selectors.get("title_selectors", []), default="")
    content = pick_best_content_text()

    snippet = first_text(
        selectors.get("snippet_selectors", [])
        + [
            "meta[property='og:description']",
            "meta[name='twitter:description']",
        ],
        default="",
    )
    snippet = sanitize_article_text(snippet)
    if not snippet:
        snippet = content[:280].strip()

    # Ensure snippet stays aligned with cleaned article text, not menu/headers.
    if snippet and snippet not in content and len(content) > 0:
        snippet = content[:280].strip()

    raw_date = first_text(selectors.get("date_selectors", []), default="")

    extracted_comments = extract_comments_from_structured_data()
    if not extracted_comments:
        extracted_comments = extract_comments_from_html()

    deduped_comments: list[dict] = []
    seen_comments: set[tuple[str, str, str]] = set()
    for comment in extracted_comments:
        text = str(comment.get("texto") or "").strip()
        if not text:
            continue
        user = str(comment.get("usuario") or "").strip()
        fecha_hora = str(comment.get("fecha_hora") or "").strip()
        key = (text.lower(), user.lower(), fecha_hora.lower())
        if key in seen_comments:
            continue
        seen_comments.add(key)
        deduped_comments.append(
            {
                "fecha_hora": fecha_hora or None,
                "usuario": user or None,
                "texto": text,
            }
        )

    return {
        "fecha_obtencion": now_ddmmyyyy(),
        "fecha_publicacion": normalize_to_ddmmyyyy(raw_date),
        "fuente": source_name,
        "raw_text": content,
        "snippet_text": snippet,
        "url_noticia": url_noticia,
        "title": title,
        "comments": deduped_comments,
        "comments_text": [item["texto"] for item in deduped_comments],
        "n_comments": len(deduped_comments),
    }
