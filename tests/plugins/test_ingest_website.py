"""Unit tests for IngestWebsitePlugin."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.events.ingest_website import (
    IngestionMode,
    IngestWebsite,
    IngestWebsiteProgress,
    IngestWebsiteResult,
    WebsiteSource,
)
from plugins.ingest_website.crawler import (
    _is_same_domain,
    _matches_patterns,
    _normalize_url,
    _should_skip_url,
    crawl,
)
from plugins.ingest_website.html_parser import extract_text, extract_title
from plugins.ingest_website.plugin import IngestWebsitePlugin
from tests.conftest import (
    MockEmbeddingsPort,
    MockKnowledgeStorePort,
    MockLLMPort,
    make_ingest_website,
)


# =====================================================================
# Event model tests (T1)
# =====================================================================


class TestEventModels:
    """Tests for the extended IngestWebsite event models."""

    def test_event_sources_deserialization(self):
        """AC1: IngestWebsite accepts sources array with per-source params."""
        payload = {
            "personaId": "vc-1",
            "sources": [
                {
                    "url": "https://docs.example.com",
                    "pageLimit": 50,
                    "maxDepth": 3,
                    "includePatterns": ["/docs/*"],
                    "excludePatterns": ["*.pdf"],
                },
                {
                    "url": "https://blog.example.com",
                },
            ],
            "mode": "FULL",
        }
        event = IngestWebsite.model_validate(payload)
        assert event.sources is not None
        assert len(event.sources) == 2
        assert event.sources[0].url == "https://docs.example.com"
        assert event.sources[0].page_limit == 50
        assert event.sources[0].max_depth == 3
        assert event.sources[0].include_patterns == ["/docs/*"]
        assert event.sources[0].exclude_patterns == ["*.pdf"]
        # Second source uses defaults
        assert event.sources[1].url == "https://blog.example.com"
        assert event.sources[1].page_limit == 20
        assert event.sources[1].max_depth == -1

    def test_event_mode_deserialization(self):
        """AC2: IngestWebsite accepts mode field."""
        payload = {
            "personaId": "vc-1",
            "sources": [{"url": "https://example.com"}],
            "mode": "FULL",
        }
        event = IngestWebsite.model_validate(payload)
        assert event.mode == IngestionMode.FULL

    def test_event_mode_default_incremental(self):
        """AC2: mode defaults to INCREMENTAL."""
        payload = {
            "personaId": "vc-1",
            "sources": [{"url": "https://example.com"}],
        }
        event = IngestWebsite.model_validate(payload)
        assert event.mode == IngestionMode.INCREMENTAL

    def test_event_backward_compat_base_url(self):
        """AC3: Legacy baseUrl-only payloads parse and synthesise sources."""
        payload = {
            "baseUrl": "https://example.com",
            "type": "website",
            "purpose": "knowledge",
            "personaId": "persona-789",
        }
        event = IngestWebsite.model_validate(payload)
        assert event.base_url == "https://example.com"
        assert event.sources is not None
        assert len(event.sources) == 1
        assert event.sources[0].url == "https://example.com"
        assert event.sources[0].page_limit == 20
        assert event.sources[0].max_depth == -1

    def test_default_page_limit_and_depth(self):
        """AC12: WebsiteSource defaults."""
        source = WebsiteSource(url="https://example.com")
        assert source.page_limit == 20
        assert source.max_depth == -1
        assert source.include_patterns is None
        assert source.exclude_patterns is None

    def test_website_source_serialization(self):
        """WebsiteSource serialises with camelCase aliases."""
        source = WebsiteSource(
            url="https://example.com",
            page_limit=10,
            max_depth=2,
        )
        dumped = source.model_dump()
        assert "pageLimit" in dumped
        assert "maxDepth" in dumped
        assert dumped["pageLimit"] == 10
        assert dumped["maxDepth"] == 2

    def test_get_source_config_json(self):
        """Source config round-trips through JSON."""
        event = IngestWebsite.model_validate({
            "personaId": "vc-1",
            "sources": [{"url": "https://a.com", "pageLimit": 5}],
        })
        config_json = event.get_source_config_json()
        parsed = json.loads(config_json)
        assert len(parsed) == 1
        assert parsed[0]["url"] == "https://a.com"
        assert parsed[0]["pageLimit"] == 5

    def test_progress_model(self):
        """AC11: IngestWebsiteProgress model is defined and serialises."""
        progress = IngestWebsiteProgress(
            source_url="https://example.com",
            status="CRAWLING",
            pages_crawled=5,
            chunks_processed=0,
        )
        dumped = progress.model_dump()
        assert dumped["sourceUrl"] == "https://example.com"
        assert dumped["status"] == "CRAWLING"
        assert dumped["pagesCrawled"] == 5


# =====================================================================
# Crawler tests (existing + new)
# =====================================================================


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


class TestPatternMatching:
    """Tests for the _matches_patterns helper."""

    def test_no_patterns_accepts_all(self):
        assert _matches_patterns("https://example.com/anything", None, None)

    def test_include_patterns_match(self):
        assert _matches_patterns(
            "https://example.com/docs/intro", ["/docs/*"], None
        )

    def test_include_patterns_reject(self):
        assert not _matches_patterns(
            "https://example.com/blog/post", ["/docs/*"], None
        )

    def test_exclude_patterns_reject(self):
        assert not _matches_patterns(
            "https://example.com/admin/settings", None, ["/admin/*"]
        )

    def test_exclude_patterns_accept(self):
        assert _matches_patterns(
            "https://example.com/docs/intro", None, ["/admin/*"]
        )

    def test_exclude_takes_priority(self):
        """Exclude is checked before include."""
        assert not _matches_patterns(
            "https://example.com/docs/secret",
            ["/docs/*"],
            ["/docs/secret"],
        )


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

    # --- New depth / pattern tests ---

    async def test_crawl_max_depth_zero(self):
        """AC4: maxDepth=0 crawls only the base page."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home page", ["https://example.com/about"]
            ),
            "https://example.com/about": _html_page("About", "About us"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=10, max_depth=0)
        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/"

    async def test_crawl_max_depth_one(self):
        """AC4: maxDepth=1 crawls base + direct links only."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home", ["https://example.com/a"]
            ),
            "https://example.com/a": _html_page(
                "A", "Page A", ["https://example.com/b"]
            ),
            "https://example.com/b": _html_page("B", "Page B"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=10, max_depth=1)
        urls = {r["url"] for r in results}
        assert "https://example.com/" in urls
        assert "https://example.com/a" in urls
        assert "https://example.com/b" not in urls

    async def test_crawl_include_patterns(self):
        """AC5: Only URLs matching includePatterns are crawled."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home",
                ["https://example.com/docs/intro", "https://example.com/blog/post"],
            ),
            "https://example.com/docs/intro": _html_page("Docs", "Documentation"),
            "https://example.com/blog/post": _html_page("Blog", "Blog post"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl(
                "https://example.com",
                page_limit=10,
                include_patterns=["/", "/docs/*"],
            )
        urls = {r["url"] for r in results}
        assert "https://example.com/" in urls
        assert "https://example.com/docs/intro" in urls
        assert "https://example.com/blog/post" not in urls

    async def test_crawl_exclude_patterns(self):
        """AC6: URLs matching excludePatterns are skipped."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home",
                ["https://example.com/admin/settings", "https://example.com/public"],
            ),
            "https://example.com/admin/settings": _html_page("Admin", "Admin page"),
            "https://example.com/public": _html_page("Public", "Public page"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl(
                "https://example.com",
                page_limit=10,
                exclude_patterns=["/admin/*"],
            )
        urls = {r["url"] for r in results}
        assert "https://example.com/" in urls
        assert "https://example.com/public" in urls
        assert "https://example.com/admin/settings" not in urls

    async def test_crawl_unlimited_page_limit(self):
        """pageLimit=-1 means unlimited."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home",
                ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
            ),
            "https://example.com/a": _html_page("A", "Page A"),
            "https://example.com/b": _html_page("B", "Page B"),
            "https://example.com/c": _html_page("C", "Page C"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=-1)
        assert len(results) == 4


# =====================================================================
# HTML parser tests
# =====================================================================


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


# =====================================================================
# Plugin tests (existing + new)
# =====================================================================


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
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert isinstance(result, IngestWebsiteResult)
        # delete_collection is no longer called — incremental dedup replaces it
        assert plugin._knowledge_store.deleted == []

    async def test_unsupported_content_skip(self, plugin):
        """Empty crawl results should still succeed."""
        event = make_ingest_website()
        with patch("plugins.ingest_website.plugin.crawl", return_value=[]):
            result = await plugin.handle(event)
        assert result.result == "success"

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()

    # --- New plugin tests ---

    async def test_full_mode_deletes_collection(self):
        """AC7: FULL mode deletes existing collection before ingesting."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        event = IngestWebsite.model_validate({
            "personaId": "vc-1",
            "sources": [{"url": "https://example.com"}],
            "mode": "FULL",
        })
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert result.result == "success"
        assert "vc-1-knowledge" in ks.deleted

    async def test_incremental_mode_no_delete(self):
        """AC8: INCREMENTAL mode does not wipe the collection."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        event = IngestWebsite.model_validate({
            "personaId": "vc-1",
            "sources": [{"url": "https://example.com"}],
            "mode": "INCREMENTAL",
        })
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert result.result == "success"
        assert ks.deleted == []

    async def test_multi_source_ingestion(self):
        """AC9: Multiple sources are each crawled and aggregated."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        event = IngestWebsite.model_validate({
            "personaId": "vc-multi",
            "sources": [
                {"url": "https://docs.example.com"},
                {"url": "https://blog.example.com"},
            ],
        })

        call_count = {"docs": 0, "blog": 0}

        async def mock_crawl(base_url, **kwargs):
            if "docs" in base_url:
                call_count["docs"] += 1
                return [{"url": "https://docs.example.com/page", "html": "<p>Docs content for testing.</p>"}]
            else:
                call_count["blog"] += 1
                return [{"url": "https://blog.example.com/post", "html": "<p>Blog content for testing.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", side_effect=mock_crawl), \
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert result.result == "success"
        assert call_count["docs"] == 1
        assert call_count["blog"] == 1
        # All docs should be in the same collection
        assert "vc-multi-knowledge" in ks.collections

    async def test_source_config_stored_in_metadata(self):
        """AC10: Source config is persisted in collection metadata."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        event = IngestWebsite.model_validate({
            "personaId": "vc-meta",
            "sources": [{"url": "https://example.com", "pageLimit": 50}],
        })
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for metadata test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert result.result == "success"

        meta = ks.collection_metadata.get("vc-meta-knowledge", {})
        assert "_source_config" in meta
        parsed = json.loads(meta["_source_config"])
        assert len(parsed) == 1
        assert parsed[0]["url"] == "https://example.com"
        assert parsed[0]["pageLimit"] == 50

        assert "_ingestion_mode" in meta
        assert meta["_ingestion_mode"] == "INCREMENTAL"

        assert "_last_ingested_at" in meta

    async def test_backward_compat_base_url_collection_naming(self):
        """Legacy baseUrl events use netloc-based collection naming."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        # Legacy event with no persona_id
        event = IngestWebsite.model_validate({
            "baseUrl": "https://example.com",
            "type": "website",
            "purpose": "knowledge",
        })
        mock_pages = [{"url": "https://example.com", "html": "<p>Legacy content for test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        assert result.result == "success"

    async def test_no_sources_returns_success(self):
        """No sources provided returns success with informative message."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        event = IngestWebsite.model_validate({
            "personaId": "vc-empty",
            "sources": [],
        })
        result = await plugin.handle(event)
        assert result.result == "success"
        assert "No sources" in result.error

    async def test_partial_source_failure(self):
        """Individual source failures don't abort remaining sources."""
        ks = MockKnowledgeStorePort()
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=ks,
        )
        event = IngestWebsite.model_validate({
            "personaId": "vc-partial",
            "sources": [
                {"url": "https://fail.example.com"},
                {"url": "https://ok.example.com"},
            ],
        })

        async def mock_crawl(base_url, **kwargs):
            if "fail" in base_url:
                raise RuntimeError("Network error")
            return [{"url": "https://ok.example.com/p", "html": "<p>OK content for partial test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", side_effect=mock_crawl), \
             patch("plugins.ingest_website.plugin.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)
        # Should still succeed because one source worked
        assert result.result == "success"
        assert "fail.example.com" in result.error
