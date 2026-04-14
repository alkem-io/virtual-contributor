"""Unit tests for IngestWebsitePlugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.events.ingest_website import IngestWebsiteResult
from plugins.ingest_website.crawler import _is_same_domain, _normalize_url, _should_skip_url, crawl
from plugins.ingest_website.html_parser import extract_text, extract_title
from plugins.ingest_website.plugin import IngestWebsitePlugin
from tests.conftest import (
    MockEmbeddingsPort,
    MockKnowledgeStorePort,
    MockLLMPort,
    make_ingest_website,
)


class TestCrawler:
    def test_domain_boundary(self):
        assert _is_same_domain("https://example.com", "https://example.com/page")
        assert not _is_same_domain("https://example.com", "https://other.com/page")

    def test_url_normalization(self):
        assert _normalize_url("https://example.com/page#section") == "https://example.com/page"
        assert _normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_skip_file_urls(self):
        assert _should_skip_url("https://example.com/file.pdf")
        assert _should_skip_url("https://example.com/image.jpg")
        assert not _should_skip_url("https://example.com/page")


def _html_page(title: str, body: str, links: list[str] | None = None) -> str:
    link_html = "".join(f'<a href="{u}">{u}</a>' for u in (links or []))
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><p>{body}</p>{link_html}</body></html>"
    )


def _mock_response(html: str, status: int = 200, content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(status, headers={"content-type": content_type}, text=html)


class TestCrawlFunction:
    """Tests for the crawl() async function with mocked HTTP transport."""

    @staticmethod
    def _patch_transport(handler):
        """Patch httpx.AsyncClient to use a mock transport handler."""
        transport = httpx.MockTransport(handler)
        return patch(
            "plugins.ingest_website.crawler.httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=transport),
        )

    async def test_single_page(self):
        html = _html_page("Home", "Welcome to the site.")
        with self._patch_transport(lambda req: _mock_response(html)):
            results = await crawl("https://example.com", page_limit=5)
        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/"

    async def test_follows_internal_links(self):
        pages = {
            "https://example.com/": _html_page("Home", "Home page", ["https://example.com/about"]),
            "https://example.com/about": _html_page("About", "About us"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            return _mock_response(pages.get(url, "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=10)
        urls = {r["url"] for r in results}
        assert len(results) == 2
        assert "https://example.com/about" in urls

    async def test_respects_page_limit(self):
        html = _html_page("Page", "Content", [
            "https://example.com/a", "https://example.com/b", "https://example.com/c",
        ])
        with self._patch_transport(lambda req: _mock_response(html)):
            results = await crawl("https://example.com", page_limit=2)
        assert len(results) <= 2

    async def test_skips_external_links(self):
        html = _html_page("Home", "Content", ["https://other-domain.com/page"])
        with self._patch_transport(lambda req: _mock_response(html)):
            results = await crawl("https://example.com", page_limit=10)
        assert all("example.com" in r["url"] for r in results)

    async def test_skips_non_html_content(self):
        with self._patch_transport(
            lambda req: httpx.Response(200, headers={"content-type": "application/json"}, text="{}")
        ):
            results = await crawl("https://example.com", page_limit=5)
        assert len(results) == 0

    async def test_handles_request_error(self):
        def error_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        with self._patch_transport(error_handler):
            results = await crawl("https://example.com", page_limit=5)
        assert len(results) == 0

    async def test_deduplicates_visited_urls(self):
        html = _html_page("Home", "Content", [
            "https://example.com/", "https://example.com/#top", "https://example.com",
        ])
        with self._patch_transport(lambda req: _mock_response(html)):
            results = await crawl("https://example.com", page_limit=10)
        assert len(results) == 1

    async def test_skips_file_links(self):
        html = _html_page("Home", "Content", [
            "https://example.com/doc.pdf", "https://example.com/img.jpg",
        ])
        with self._patch_transport(lambda req: _mock_response(html)):
            results = await crawl("https://example.com", page_limit=10)
        assert len(results) == 1  # Only the root page


class TestHTMLParser:
    def test_extract_text(self):
        html = "<html><body><p>Hello world this is content.</p><p>More content here for testing.</p></body></html>"
        text = extract_text(html)
        assert "Hello world" in text

    def test_extract_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        assert extract_title(html) == "My Page"

    def test_extract_title_fallback_h1(self):
        html = "<html><body><h1>Heading</h1></body></html>"
        assert extract_title(html) == "Heading"

    def test_strips_scripts(self):
        html = "<html><body><script>alert('x')</script><p>Actual content for extraction.</p></body></html>"
        text = extract_text(html)
        assert "alert" not in text


class TestIngestWebsitePlugin:
    @pytest.fixture
    def plugin(self):
        return IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
        )

    async def test_pipeline_composition(self, plugin):
        """Verify IngestEngine is used with incremental dedup (no delete_collection)."""
        event = make_ingest_website()
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for ingestion test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert isinstance(result, IngestWebsiteResult)
        # delete_collection is no longer called — incremental dedup replaces it
        assert plugin._knowledge_store.deleted == []
        assert "example.com-knowledge" in plugin._knowledge_store.collections

    async def test_empty_crawl_runs_cleanup(self):
        """When crawl returns [], cleanup deletes pre-existing chunks."""
        store = MockKnowledgeStorePort()
        collection = "example.com-knowledge"
        await store.ingest(
            collection=collection,
            documents=["old website content"],
            metadatas=[{"documentId": "https://example.com/old", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["old-hash-1"],
            embeddings=[[0.1] * 384],
        )
        assert len(store.collections[collection]) == 1

        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
        )

        event = make_ingest_website()
        with patch("plugins.ingest_website.plugin.crawl", return_value=[]):
            result = await plugin.handle(event)

        assert isinstance(result, IngestWebsiteResult)
        assert result.result == "success"
        # All pre-existing chunks should have been deleted
        assert len(store.collections.get(collection, [])) == 0

    async def test_empty_extract_runs_cleanup(self):
        """When crawl returns pages but extraction yields nothing, cleanup runs."""
        store = MockKnowledgeStorePort()
        collection = "example.com-knowledge"
        await store.ingest(
            collection=collection,
            documents=["stale content"],
            metadatas=[{"documentId": "https://example.com/stale", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["stale-hash"],
            embeddings=[[0.1] * 384],
        )

        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
        )

        event = make_ingest_website()
        # Crawl returns pages, but all pages have empty/whitespace text
        empty_pages = [{"url": "https://example.com/empty", "html": "<html><body>   </body></html>"}]
        with patch("plugins.ingest_website.plugin.crawl", return_value=empty_pages):
            result = await plugin.handle(event)

        assert result.result == "success"
        assert len(store.collections.get(collection, [])) == 0

    async def test_empty_crawl_returns_success(self, plugin):
        """Empty-but-successful crawl returns IngestionResult.SUCCESS."""
        event = make_ingest_website()
        with patch("plugins.ingest_website.plugin.crawl", return_value=[]):
            result = await plugin.handle(event)
        assert result.result == "success"

    async def test_crawl_failure_no_cleanup(self):
        """When crawl raises, return failure without running cleanup."""
        store = MockKnowledgeStorePort()
        collection = "example.com-knowledge"
        await store.ingest(
            collection=collection,
            documents=["preserved content"],
            metadatas=[{"documentId": "https://example.com/page", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["hash-1"],
            embeddings=[[0.1] * 384],
        )

        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
        )

        event = make_ingest_website()
        with patch(
            "plugins.ingest_website.plugin.crawl",
            side_effect=RuntimeError("Connection timeout"),
        ):
            result = await plugin.handle(event)

        assert result.result == "failure"
        assert "Connection timeout" in result.error
        # Store should be untouched — no cleanup ran
        assert len(store.collections[collection]) == 1

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()
