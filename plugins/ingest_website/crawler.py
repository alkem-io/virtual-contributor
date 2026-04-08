"""Recursive web crawler with domain boundary enforcement."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from fnmatch import fnmatch
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

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


def _matches_patterns(
    url: str,
    include_patterns: list[str] | None,
    exclude_patterns: list[str] | None,
) -> bool:
    """Check whether a URL passes include/exclude glob filters.

    Patterns are matched against the **path** component of the URL
    (e.g. ``/docs/intro``).  Uses :func:`fnmatch.fnmatch` for glob
    semantics (``*``, ``?``, ``[...]``).

    Rules:
    - If *exclude_patterns* is given and any pattern matches, reject.
    - If *include_patterns* is given, at least one pattern must match.
    - If neither is given, accept.
    """
    path = urlparse(url).path

    if exclude_patterns:
        for pat in exclude_patterns:
            if fnmatch(path, pat):
                return False

    if include_patterns:
        return any(fnmatch(path, pat) for pat in include_patterns)

    return True


async def _is_safe_url(url: str) -> bool:
    """Block private/reserved network targets to prevent SSRF.

    Only allows http/https schemes and rejects URLs that resolve
    to loopback, RFC1918, link-local, or cloud metadata addresses.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Hostname, not an IP — resolve without blocking the event loop
        try:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo, hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            for _, _, _, _, sockaddr in resolved:
                addr = ipaddress.ip_address(sockaddr[0])
                if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                    return False
            return True
        except socket.gaierror:
            return False
    else:
        return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved)


async def crawl(
    base_url: str,
    page_limit: int = 20,
    max_depth: int = -1,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[dict]:
    """Crawl a website recursively within domain boundaries.

    Parameters
    ----------
    base_url:
        Starting URL.
    page_limit:
        Maximum number of pages to fetch.  ``-1`` means unlimited.
    max_depth:
        Maximum link-follow depth from *base_url*.
        ``0`` = base page only, ``1`` = base + direct links,
        ``-1`` = unlimited (default).
    include_patterns:
        If given, only URLs whose **path** matches at least one glob
        pattern are crawled.
    exclude_patterns:
        URLs whose path matches any of these glob patterns are skipped.

    Returns
    -------
    list[dict]
        List of ``{"url": str, "html": str}`` dicts.
    """
    if not await _is_safe_url(base_url):
        logger.warning("Blocked unsafe base URL: %s", base_url)
        return []

    visited: set[str] = set()
    results: list[dict] = []
    # Queue entries: (url, depth)
    queue: list[tuple[str, int]] = [(_normalize_url(base_url), 0)]

    unlimited_pages = page_limit == -1

    async with httpx.AsyncClient(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": "AlkemioBot/1.0"},
    ) as client:
        while queue and (unlimited_pages or len(results) < page_limit):
            url, depth = queue.pop(0)
            normalized = _normalize_url(url)

            if normalized in visited:
                continue
            if _should_skip_url(normalized):
                continue
            if not _is_same_domain(base_url, normalized):
                continue
            if not _matches_patterns(normalized, include_patterns, exclude_patterns):
                continue

            visited.add(normalized)

            try:
                response = await client.get(normalized)
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type:
                    continue

                html = response.text
                results.append({"url": normalized, "html": html})

                # Only follow links if we haven't hit max_depth
                if max_depth != -1 and depth >= max_depth:
                    continue

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
                        queue.append((full_normalized, depth + 1))

            except Exception as exc:
                logger.warning("Failed to crawl %s: %s", normalized, exc)

    logger.info("Crawled %d pages from %s", len(results), base_url)
    return results
