"""Unit tests for IngestWebsitePlugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from core.events.ingest_website import (
    IngestionMode,
    IngestWebsite,
    IngestWebsiteResult,
    SourceResult,
)
from plugins.ingest_website.crawler import (
    _is_same_domain,
    _matches_any_pattern,
    _normalize_url,
    _should_follow_url,
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
    make_website_source,
)


# ---------------------------------------------------------------------------
# Crawler helper tests
# ---------------------------------------------------------------------------


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
    """Tests for URL pattern matching helpers."""

    def test_matches_any_pattern_positive(self):
        assert _matches_any_pattern("https://example.com/docs/page", ["/docs/*"])

    def test_matches_any_pattern_negative(self):
        assert not _matches_any_pattern("https://example.com/about", ["/docs/*"])

    def test_matches_any_pattern_multiple(self):
        assert _matches_any_pattern(
            "https://example.com/blog/post",
            ["/docs/*", "/blog/*"],
        )

    def test_matches_any_pattern_wildcard_extension(self):
        assert _matches_any_pattern("https://example.com/file.pdf", ["*.pdf"])

    def test_should_follow_no_patterns(self):
        """No patterns means follow everything."""
        assert _should_follow_url("https://example.com/any", None, None)

    def test_should_follow_include_match(self):
        assert _should_follow_url(
            "https://example.com/docs/page", ["/docs/*"], None
        )

    def test_should_follow_include_no_match(self):
        assert not _should_follow_url(
            "https://example.com/about", ["/docs/*"], None
        )

    def test_should_follow_exclude_match(self):
        assert not _should_follow_url(
            "https://example.com/admin/page", None, ["/admin/*"]
        )

    def test_should_follow_exclude_overrides_include(self):
        """Exclude takes precedence over include."""
        assert not _should_follow_url(
            "https://example.com/docs/secret",
            ["/docs/*"],
            ["/docs/secret"],
        )


# ---------------------------------------------------------------------------
# HTML parser tests
# ---------------------------------------------------------------------------


def _html_page(title: str, body: str, links: list[str] | None = None) -> str:
    link_html = "".join(f'<a href="{u}">{u}</a>' for u in (links or []))
    return (
        f"<html><head><title>{title}</title></head>"
        f"<body><p>{body}</p>{link_html}</body></html>"
    )


def _mock_response(html: str, status: int = 200, content_type: str = "text/html") -> httpx.Response:
    return httpx.Response(status, headers={"content-type": content_type}, text=html)


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


# ---------------------------------------------------------------------------
# Crawl function tests (with mocked HTTP)
# ---------------------------------------------------------------------------


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

    # --- maxDepth tests ---

    async def test_max_depth_zero_base_only(self):
        """max_depth=0 returns only the base page, no link following."""
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

    async def test_max_depth_one(self):
        """max_depth=1 returns base + direct links but not links from depth-1."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home page", ["https://example.com/about"]
            ),
            "https://example.com/about": _html_page(
                "About", "About us", ["https://example.com/deep"]
            ),
            "https://example.com/deep": _html_page("Deep", "Deep page"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=10, max_depth=1)
        urls = {r["url"] for r in results}
        assert "https://example.com/" in urls
        assert "https://example.com/about" in urls
        assert "https://example.com/deep" not in urls

    async def test_max_depth_unlimited_default(self):
        """Default max_depth=-1 follows all links (backward compat)."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home page", ["https://example.com/a"]
            ),
            "https://example.com/a": _html_page(
                "A", "Page A", ["https://example.com/b"]
            ),
            "https://example.com/b": _html_page("B", "Page B"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=10)
        assert len(results) == 3

    # --- Pattern filtering tests ---

    async def test_include_patterns_filter(self):
        """Only links matching include patterns are followed."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home page",
                ["https://example.com/docs/guide", "https://example.com/about"],
            ),
            "https://example.com/docs/guide": _html_page("Guide", "Guide content"),
            "https://example.com/about": _html_page("About", "About us"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl(
                "https://example.com",
                page_limit=10,
                include_patterns=["/docs/*"],
            )
        urls = {r["url"] for r in results}
        # Base URL always crawled
        assert "https://example.com/" in urls
        # Matching pattern followed
        assert "https://example.com/docs/guide" in urls
        # Non-matching pattern skipped
        assert "https://example.com/about" not in urls

    async def test_exclude_patterns_filter(self):
        """Links matching exclude patterns are skipped."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home page",
                ["https://example.com/docs/guide", "https://example.com/admin/panel"],
            ),
            "https://example.com/docs/guide": _html_page("Guide", "Guide content"),
            "https://example.com/admin/panel": _html_page("Admin", "Admin panel"),
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
        assert "https://example.com/docs/guide" in urls
        assert "https://example.com/admin/panel" not in urls

    async def test_exclude_overrides_include(self):
        """Exclude patterns take precedence over include patterns."""
        pages = {
            "https://example.com/": _html_page(
                "Home", "Home page",
                ["https://example.com/docs/public", "https://example.com/docs/secret"],
            ),
            "https://example.com/docs/public": _html_page("Public", "Public docs"),
            "https://example.com/docs/secret": _html_page("Secret", "Secret docs"),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return _mock_response(pages.get(str(request.url), "<html></html>"))

        with self._patch_transport(handler):
            results = await crawl(
                "https://example.com",
                page_limit=10,
                include_patterns=["/docs/*"],
                exclude_patterns=["/docs/secret"],
            )
        urls = {r["url"] for r in results}
        assert "https://example.com/docs/public" in urls
        assert "https://example.com/docs/secret" not in urls

    async def test_base_url_always_crawled_with_include(self):
        """Base URL is always crawled even if it doesn't match include patterns."""
        html = _html_page("Home", "Home page content for testing extraction.")
        with self._patch_transport(lambda req: _mock_response(html)):
            results = await crawl(
                "https://example.com",
                page_limit=10,
                include_patterns=["/docs/*"],
            )
        assert len(results) == 1
        assert results[0]["url"] == "https://example.com/"


# ---------------------------------------------------------------------------
# Event model tests
# ---------------------------------------------------------------------------


class TestIngestWebsiteEvent:
    """Tests for the IngestWebsite event model."""

    def test_backward_compat_base_url_only(self):
        """Legacy format with baseUrl still works."""
        event = make_ingest_website()
        assert len(event.sources) == 1
        assert event.sources[0].url == "https://example.com"
        assert event.mode == IngestionMode.INCREMENTAL

    def test_new_format_with_sources(self):
        """New format with explicit sources list."""
        event = make_ingest_website(
            baseUrl=None,
            sources=[
                {"url": "https://docs.example.com", "pageLimit": 50, "maxDepth": 2},
                {"url": "https://blog.example.com", "maxDepth": 1},
            ],
        )
        assert len(event.sources) == 2
        assert event.sources[0].url == "https://docs.example.com"
        assert event.sources[0].page_limit == 50
        assert event.sources[0].max_depth == 2
        assert event.sources[1].url == "https://blog.example.com"
        assert event.sources[1].page_limit is None
        assert event.sources[1].max_depth == 1

    def test_mode_default_incremental(self):
        event = make_ingest_website()
        assert event.mode == IngestionMode.INCREMENTAL

    def test_mode_full(self):
        event = make_ingest_website(mode="full")
        assert event.mode == IngestionMode.FULL

    def test_source_result_serialization(self):
        sr = SourceResult(url="https://example.com", pages_processed=5)
        dumped = sr.model_dump()
        assert dumped["pagesProcessed"] == 5
        assert dumped["url"] == "https://example.com"
        assert dumped["error"] == ""

    def test_website_source_defaults(self):
        source = make_website_source()
        assert source.page_limit is None
        assert source.max_depth == -1
        assert source.include_patterns is None
        assert source.exclude_patterns is None

    def test_website_source_with_patterns(self):
        source = make_website_source(
            includePatterns=["/docs/*"],
            excludePatterns=["*.pdf"],
        )
        assert source.include_patterns == ["/docs/*"]
        assert source.exclude_patterns == ["*.pdf"]

    def test_result_with_source_results(self):
        result = IngestWebsiteResult(
            source_results=[
                SourceResult(url="https://a.com", pages_processed=3),
                SourceResult(url="https://b.com", pages_processed=5, error="timeout"),
            ]
        )
        dumped = result.model_dump()
        assert len(dumped["sourceResults"]) == 2
        assert dumped["sourceResults"][0]["pagesProcessed"] == 3
        assert dumped["sourceResults"][1]["error"] == "timeout"


# ---------------------------------------------------------------------------
# Plugin tests
# ---------------------------------------------------------------------------


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
        assert "persona-789-knowledge" in plugin._knowledge_store.collections

    async def test_unsupported_content_skip(self, plugin):
        """Empty crawl results should still succeed."""
        event = make_ingest_website()
        with patch("plugins.ingest_website.plugin.crawl", return_value=[]):
            result = await plugin.handle(event)
        assert result.result == "success"

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()

    async def test_multi_source_crawl(self, plugin):
        """Multiple sources are crawled and documents merged."""
        event = make_ingest_website(
            baseUrl=None,
            sources=[
                {"url": "https://docs.example.com"},
                {"url": "https://blog.example.com"},
            ],
        )

        call_count = 0

        async def mock_crawl(base_url, **kwargs):
            nonlocal call_count
            call_count += 1
            return [
                {
                    "url": f"{base_url}/page",
                    "html": f"<p>Content from {base_url} for testing purposes.</p>",
                }
            ]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", side_effect=mock_crawl), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)

        assert call_count == 2
        assert len(result.source_results) == 2
        assert result.source_results[0].pages_processed == 1
        assert result.source_results[1].pages_processed == 1
        assert result.result == "success"

    async def test_full_mode_deletes_collection(self, plugin):
        """FULL mode deletes the collection before ingesting."""
        event = make_ingest_website(mode="full")
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for full mode test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)

        assert "persona-789-knowledge" in plugin._knowledge_store.deleted
        assert result.result == "success"

    async def test_incremental_mode_no_delete(self, plugin):
        """INCREMENTAL mode does not delete the collection."""
        event = make_ingest_website(mode="incremental")
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for incremental test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)

        assert plugin._knowledge_store.deleted == []
        assert result.result == "success"

    async def test_source_config_stored(self, plugin):
        """Source config is stored as sentinel chunk."""
        event = make_ingest_website()
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for config storage test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("core.config.BaseConfig", return_value=mock_config):
            await plugin.handle(event)

        collection = plugin._knowledge_store.collections.get("persona-789-knowledge", [])
        config_entries = [e for e in collection if e["id"] == "__source_config__"]
        assert len(config_entries) == 1
        assert config_entries[0]["metadata"]["embeddingType"] == "config"

    async def test_result_includes_source_results(self, plugin):
        """Result includes per-source statistics."""
        event = make_ingest_website()
        mock_pages = [{"url": "https://example.com", "html": "<p>Content for result reporting test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)

        assert len(result.source_results) == 1
        assert result.source_results[0].url == "https://example.com"
        assert result.source_results[0].pages_processed == 1

    async def test_per_source_page_limit_fallback(self, plugin):
        """Per-source pageLimit=None falls back to default."""
        event = make_ingest_website(
            baseUrl=None,
            sources=[{"url": "https://example.com"}],
        )

        crawl_kwargs = {}

        async def mock_crawl(base_url, **kwargs):
            crawl_kwargs.update(kwargs)
            return [{"url": base_url, "html": "<p>Content for page limit test purposes.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", side_effect=mock_crawl), \
             patch("core.config.BaseConfig", return_value=mock_config):
            await plugin.handle(event)

        assert crawl_kwargs["page_limit"] == 20  # default

    async def test_per_source_page_limit_override(self, plugin):
        """Per-source pageLimit overrides the default."""
        event = make_ingest_website(
            baseUrl=None,
            sources=[{"url": "https://example.com", "pageLimit": 50}],
        )

        crawl_kwargs = {}

        async def mock_crawl(base_url, **kwargs):
            crawl_kwargs.update(kwargs)
            return [{"url": base_url, "html": "<p>Content for limit override test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", side_effect=mock_crawl), \
             patch("core.config.BaseConfig", return_value=mock_config):
            await plugin.handle(event)

        assert crawl_kwargs["page_limit"] == 50

    async def test_legacy_event_still_works(self, plugin):
        """Legacy event with baseUrl and no sources still works end-to-end."""
        event = IngestWebsite.model_validate({
            "baseUrl": "https://legacy.example.com",
            "type": "website",
            "purpose": "knowledge",
            "personaId": "legacy-persona",
        })

        assert len(event.sources) == 1
        assert event.sources[0].url == "https://legacy.example.com"
        assert event.mode == IngestionMode.INCREMENTAL

        mock_pages = [
            {"url": "https://legacy.example.com", "html": "<p>Legacy content for testing.</p>"}
        ]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)

        assert result.result == "success"
        assert len(result.source_results) == 1

    async def test_crawl_source_error_handling(self, plugin):
        """Source crawl failure is captured in source results."""
        event = make_ingest_website(
            baseUrl=None,
            sources=[
                {"url": "https://good.example.com"},
                {"url": "https://bad.example.com"},
            ],
        )

        async def mock_crawl(base_url, **kwargs):
            if "bad" in base_url:
                raise RuntimeError("Connection failed")
            return [{"url": base_url, "html": "<p>Good content for error handling test.</p>"}]

        mock_config = MagicMock()
        mock_config.summarize_concurrency = 0

        with patch("plugins.ingest_website.plugin.crawl", side_effect=mock_crawl), \
             patch("core.config.BaseConfig", return_value=mock_config):
            result = await plugin.handle(event)

        assert len(result.source_results) == 2
        assert result.source_results[0].pages_processed == 1
        assert result.source_results[0].error == ""
        assert "Connection failed" in result.source_results[1].error
