"""HTML content extraction using BeautifulSoup."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag


SEMANTIC_TAGS = {"p", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "title", "li"}

# Elements to remove entirely before extraction
_STRIP_TAGS = ["script", "style", "nav", "footer", "header", "aside", "form", "dialog", "noscript"]

# Class/ID patterns that indicate boilerplate (cookie banners, popups, etc.)
_BOILERPLATE_RE = re.compile(
    r"cookie|consent|banner|popup|modal|gdpr|newsletter|subscribe|"
    r"sign-?up|opt-?in|privacy-?notice|bottom-?bar|snackbar",
    re.IGNORECASE,
)


def _has_boilerplate_attr(tag: Tag) -> bool:
    """Return True if the tag's class or id matches a boilerplate pattern."""
    classes = tag.get("class") or []
    if any(_BOILERPLATE_RE.search(c) for c in classes):
        return True
    tag_id = tag.get("id") or ""
    return bool(_BOILERPLATE_RE.search(tag_id))


def extract_text(html: str) -> str:
    """Extract meaningful text content from HTML.

    Focuses on semantic tags: p, section, article, h1-h6, title, li.
    Removes boilerplate elements (cookie banners, modals, forms, etc.)
    before extraction.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove structural boilerplate tags
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    # Remove elements with cookie/consent/banner class or id
    for tag in soup.find_all(_has_boilerplate_attr):
        tag.decompose()

    parts: list[str] = []
    for tag in soup.find_all(SEMANTIC_TAGS):
        text = tag.get_text(strip=True)
        if text and len(text) > 10:  # Skip very short fragments
            parts.append(text)

    # Fallback: if semantic extraction yielded little, use full text
    if len(parts) < 3:
        full_text = soup.get_text(separator="\n", strip=True)
        return full_text

    return "\n\n".join(parts)


def remove_cross_page_boilerplate(
    texts: list[str],
    threshold: float = 0.5,
    min_pages: int = 4,
) -> list[str]:
    """Remove paragraphs that appear on many pages (boilerplate).

    Splits each text into paragraphs, counts how many pages each
    paragraph appears on, and strips paragraphs that appear on more
    than ``threshold`` fraction of pages.  Catches cookie policy text,
    repeated CTAs, and other boilerplate that the HTML-level cleanup
    missed.

    Only activates when there are >= ``min_pages`` pages — on small
    sites, repeated content is more likely to be legitimate.
    """
    if len(texts) < min_pages:
        return texts

    def _normalize(p: str) -> str:
        return " ".join(p.split()).lower()

    # Count how many pages each normalized paragraph appears on
    para_page_count: dict[str, int] = {}
    for text in texts:
        seen_in_page: set[str] = set()
        for para in text.split("\n\n"):
            key = _normalize(para)
            if len(key) < 20:
                continue
            if key not in seen_in_page:
                seen_in_page.add(key)
                para_page_count[key] = para_page_count.get(key, 0) + 1

    cutoff = threshold * len(texts)
    boilerplate = {key for key, count in para_page_count.items() if count > cutoff}

    if not boilerplate:
        return texts

    cleaned: list[str] = []
    for text in texts:
        paras = text.split("\n\n")
        kept = [p for p in paras if _normalize(p) not in boilerplate]
        cleaned.append("\n\n".join(kept))

    return cleaned


def extract_title(html: str) -> str:
    """Extract the page title from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    h1_tag = soup.find("h1")
    if h1_tag:
        return h1_tag.get_text(strip=True)
    return ""
