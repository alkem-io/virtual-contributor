"""HTML content extraction using BeautifulSoup."""

from __future__ import annotations

from bs4 import BeautifulSoup


SEMANTIC_TAGS = {"p", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "title", "li"}


def extract_text(html: str) -> str:
    """Extract meaningful text content from HTML.

    Focuses on semantic tags: p, section, article, h1-h6, title, li.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "footer", "header"]):
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
