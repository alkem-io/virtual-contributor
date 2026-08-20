"""Recursive web crawler with domain boundary enforcement."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from plugins.url_guard import RefusalCategory, check_destination, guarded_fetch

logger = logging.getLogger(__name__)

# File extensions to skip (65+ extensions)
SKIP_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".webp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".wav",
    ".exe", ".msi", ".dmg", ".deb", ".rpm",
    ".css", ".js", ".json", ".xml", ".csv",
    ".woff", ".woff2", ".ttf", ".eot",
    ".iso", ".img", ".bin",
    ".odt", ".ods", ".odp", ".rtf", ".txt",
    ".apk", ".ipa",
    ".sql", ".db", ".sqlite",
    ".log", ".bak", ".tmp",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".bash", ".ps1", ".bat", ".cmd",
    ".py", ".rb", ".java", ".c", ".cpp", ".h", ".go", ".rs",
}


def _normalize_url(url: str) -> str:
    """Normalize URL by removing fragments and trailing slashes."""
    parsed = urlparse(url)
    normalized = parsed._replace(fragment="")
    path = normalized.path.rstrip("/") or "/"
    return normalized._replace(path=path).geturl()


def _is_same_domain(base_url: str, url: str) -> bool:
    """Check if URL belongs to the same domain as base."""
    return urlparse(base_url).netloc == urlparse(url).netloc


def _should_skip_url(url: str) -> bool:
    """Check if URL points to a file that should be skipped."""
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in SKIP_EXTENSIONS)


class CrawlError(Exception):
    """Raised when the crawl fails to reach the target site."""


async def crawl(
    base_url: str,
    page_limit: int = 20,
) -> list[dict]:
    """Crawl a website recursively within domain boundaries.

    Returns list of {"url": str, "html": str} dicts.

    Raises ``CrawlError`` when the base URL is unreachable (e.g. network
    error, DNS failure) so callers can distinguish a genuine empty site
    from a transient failure.
    """
    decision = await check_destination(base_url, deployment_host=None)
    if not decision.allowed:
        logger.warning(
            "Blocked unsafe base URL: category=%s scheme=%s host=%s",
            decision.reason.value if decision.reason else "",
            urlparse(base_url).scheme.lower(),
            decision.host,
        )
        return []

    visited: set[str] = set()
    results: list[dict] = []
    queue = [_normalize_url(base_url)]
    is_first_request = True

    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as client:
        while queue and len(results) < page_limit:
            url = queue.pop(0)
            normalized = _normalize_url(url)

            if normalized in visited:
                continue
            if _should_skip_url(normalized):
                continue
            if not _is_same_domain(base_url, normalized):
                continue

            visited.add(normalized)

            result = await guarded_fetch(
                normalized,
                max_bytes=10 * 1024 * 1024,
                request_headers={"User-Agent": "AlkemioBot/1.0"},
                content_type_policy=lambda content_type, _: "text/html" in content_type,
                redirect_policy=lambda target: _is_same_domain(base_url, target),
                client=client,
            )
            if result.body is None:
                if is_first_request and result.reason is RefusalCategory.TRANSPORT and result.status_code is None:
                    raise CrawlError(
                        f"Failed to reach base URL {normalized}: {result.error_type or 'transport error'}"
                    )
                if result.reason is RefusalCategory.TRANSPORT and result.status_code is None:
                    logger.warning("Failed to crawl %s: %s", normalized, result.error_type)
                is_first_request = False
                continue

            html = result.body.decode("utf-8", errors="replace")
            # The guarded executor returns the validated final redirect target.
            final_url = _normalize_url(result.url)
            results.append({"url": final_url, "html": html})

            # Extract links
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = link["href"]
                full_url = urljoin(normalized, href)
                full_normalized = _normalize_url(full_url)
                if (
                    full_normalized not in visited
                    and _is_same_domain(base_url, full_normalized)
                    and not _should_skip_url(full_normalized)
                ):
                    queue.append(full_normalized)

            is_first_request = False

    logger.info("Crawled %d pages from %s", len(results), base_url)
    return results
