"""Unit tests for IngestWebsitePlugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from core.events.ingest_website import IngestWebsiteResult
from plugins.ingest_website.crawler import CrawlError, _is_same_domain, _normalize_url, _should_skip_url, crawl
from plugins.ingest_website.html_parser import extract_text, extract_title, remove_cross_page_boilerplate
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
        """Base URL request failure raises CrawlError instead of returning []."""
        def error_handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        with self._patch_transport(error_handler):
            with pytest.raises(CrawlError, match="Failed to reach base URL"):
                await crawl("https://example.com", page_limit=5)

    async def test_subsequent_page_error_continues(self):
        """Errors on pages after the first are logged and skipped."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            url = str(request.url)
            if "about" in url:
                raise httpx.ConnectError("Connection refused")
            return _mock_response(
                _html_page("Home", "Content", ["https://example.com/about"])
            )

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=5)
        # Only the first page succeeds; the second fails but is skipped
        assert len(results) == 1

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

    # -- Spec 021 T017: strip aside, form, dialog, noscript --

    def test_strips_aside(self):
        html = "<html><body><aside>Sidebar content here.</aside><p>Main content for the page.</p><p>More main content here.</p><p>Third paragraph of content.</p></body></html>"
        text = extract_text(html)
        assert "Sidebar" not in text
        assert "Main content" in text

    def test_strips_form(self):
        html = "<html><body><form><input type='text'/><button>Submit</button></form><p>Actual page content here.</p><p>Second paragraph content here.</p><p>Third paragraph of content.</p></body></html>"
        text = extract_text(html)
        assert "Submit" not in text
        assert "Actual page" in text

    def test_strips_dialog(self):
        html = "<html><body><dialog open>Sign in to continue</dialog><p>Real page content here.</p><p>Another paragraph of content.</p><p>Third paragraph of content.</p></body></html>"
        text = extract_text(html)
        assert "Sign in" not in text
        assert "Real page" in text

    def test_strips_noscript(self):
        html = "<html><body><noscript>Please enable JavaScript</noscript><p>Content visible always.</p><p>More visible content here.</p><p>Third paragraph of content.</p></body></html>"
        text = extract_text(html)
        assert "enable JavaScript" not in text
        assert "Content visible" in text

    # -- Spec 021 T018: cookie/consent/banner class/ID patterns --

    def test_strips_cookie_banner_by_class(self):
        html = (
            '<html><body>'
            '<div class="cookie-banner">We use cookies</div>'
            '<p>Important page content here.</p>'
            '<p>Second paragraph of content.</p>'
            '<p>Third paragraph of content.</p>'
            '</body></html>'
        )
        text = extract_text(html)
        assert "cookies" not in text
        assert "Important" in text

    def test_strips_consent_by_id(self):
        html = (
            '<html><body>'
            '<div id="gdpr-consent-modal">Accept our privacy policy</div>'
            '<p>Main article content here.</p>'
            '<p>Second paragraph of content.</p>'
            '<p>Third paragraph of content.</p>'
            '</body></html>'
        )
        text = extract_text(html)
        assert "privacy policy" not in text
        assert "Main article" in text

    def test_strips_newsletter_popup(self):
        html = (
            '<html><body>'
            '<div class="newsletter-popup">Subscribe to our newsletter</div>'
            '<p>Valuable content for users.</p>'
            '<p>More valuable content here.</p>'
            '<p>Third valuable paragraph here.</p>'
            '</body></html>'
        )
        text = extract_text(html)
        assert "Subscribe" not in text
        assert "Valuable content" in text

    # -- Spec 021 T023: semantic extraction unaffected by boilerplate removal --

    def test_semantic_extraction_preserved_after_boilerplate_removal(self):
        """Semantic tags (p, section, article, h1-h6) extracted normally after boilerplate strip."""
        html = (
            '<html><body>'
            '<nav>Navigation links here</nav>'
            '<div class="cookie-consent">Accept cookies</div>'
            '<h1>Article Title Here Now</h1>'
            '<section><p>First paragraph of the article content.</p></section>'
            '<article><p>Second paragraph in article tag content.</p></article>'
            '<p>Third standalone paragraph with content.</p>'
            '<footer>Footer content here</footer>'
            '</body></html>'
        )
        text = extract_text(html)
        assert "Article Title" in text
        assert "First paragraph" in text
        assert "Second paragraph" in text
        assert "Third standalone" in text
        assert "Navigation" not in text
        assert "cookies" not in text
        assert "Footer" not in text

    # -- Spec 021 T024: fallback extraction after boilerplate strip --

    def test_fallback_extraction_works_after_boilerplate_strip(self):
        """When semantic tags yield <3 parts, fallback to full text still works."""
        html = (
            '<html><body>'
            '<div class="cookie-banner">Cookie stuff here</div>'
            '<div>This is content without semantic tags but has enough text.</div>'
            '</body></html>'
        )
        text = extract_text(html)
        # Fallback path: full text extraction
        assert "content without semantic tags" in text
        assert "Cookie stuff" not in text


# ---------------------------------------------------------------------------
# Spec 021 T019-T020: cross-page paragraph deduplication
# ---------------------------------------------------------------------------

class TestCrossPageBoilerplate:
    """Tests for remove_cross_page_boilerplate()."""

    def test_removes_paragraphs_above_threshold(self):
        """Paragraphs appearing on >50% of pages are removed."""
        boilerplate = "This is our cookie policy notice that appears everywhere."
        unique = [f"Unique content for page {i} with enough length." for i in range(6)]
        texts = [f"{u}\n\n{boilerplate}" for u in unique]

        cleaned = remove_cross_page_boilerplate(texts, threshold=0.5, min_pages=4)

        for text in cleaned:
            assert "cookie policy" not in text
        for i, text in enumerate(cleaned):
            assert f"page {i}" in text

    def test_skips_when_below_min_pages(self):
        """When fewer than min_pages texts, returns unchanged."""
        boilerplate = "Repeated paragraph on every single page."
        texts = [f"Page {i} content.\n\n{boilerplate}" for i in range(3)]

        cleaned = remove_cross_page_boilerplate(texts, threshold=0.5, min_pages=4)

        # Should be unchanged — not enough pages to activate
        assert cleaned == texts

    def test_keeps_unique_paragraphs(self):
        """Paragraphs on fewer than threshold pages are kept."""
        texts = [
            "Unique A content with enough characters.\n\nShared across most pages content.",
            "Unique B content with enough characters.\n\nShared across most pages content.",
            "Unique C content with enough characters.\n\nShared across most pages content.",
            "Unique D content with enough characters.\n\nShared across most pages content.",
            "Unique E content with enough characters.\n\nOnly on this page special content.",
        ]

        cleaned = remove_cross_page_boilerplate(texts, threshold=0.5, min_pages=4)

        # "Only on this page" appears on 1/5 pages — below threshold, should stay
        assert "Only on this page" in cleaned[4]
        # "Shared across most" appears on 4/5 pages — above threshold, should go
        assert "Shared across most" not in cleaned[0]

    def test_short_paragraphs_ignored(self):
        """Paragraphs under 20 chars are not counted or removed."""
        texts = [f"Short\n\nActual content that is unique for page {i}." for i in range(5)]

        cleaned = remove_cross_page_boilerplate(texts, threshold=0.5, min_pages=4)

        # "Short" is under 20 chars — should survive even though it's on every page
        for text in cleaned:
            assert "Short" in text


# ---------------------------------------------------------------------------
# Spec 021 T021: empty documents filtered after cross-page dedup
# ---------------------------------------------------------------------------

class TestEmptyDocFilterAfterDedup:
    """Verify the plugin filters empty documents after cross-page dedup."""

    async def test_empty_docs_filtered_after_dedup(self):
        """Documents emptied by cross-page dedup are excluded from the pipeline."""
        # Build pages where one page is entirely boilerplate
        boilerplate = "This cookie policy applies to all visitors of our site."
        pages = []
        for i in range(5):
            if i == 0:
                # This page has only boilerplate — will be empty after dedup
                pages.append({
                    "url": f"https://example.com/page{i}",
                    "html": f"<p>{boilerplate}</p>",
                })
            else:
                pages.append({
                    "url": f"https://example.com/page{i}",
                    "html": f"<p>Unique content for page number {i} here.</p><p>More content for page {i}.</p><p>Even more for page {i}.</p>\n\n<p>{boilerplate}</p>",
                })

        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
        )
        event = make_ingest_website()

        with patch("plugins.ingest_website.plugin.crawl", return_value=pages), \
             patch("plugins.ingest_website.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = AsyncMock(
                return_value=MagicMock(success=True, errors=[])
            )
            await plugin.handle(event)

        # Verify documents passed to engine.run exclude empty docs
        assert mock_engine.called
        run_args, _ = mock_engine.return_value.run.await_args
        docs = run_args[0]
        assert len(docs) == 4
        assert all(d.content.strip() for d in docs)


# ---------------------------------------------------------------------------
# Spec 021 T022: crawler records final URL after redirect
# ---------------------------------------------------------------------------

class TestCrawlerRedirectURL:
    """Verify crawler uses response.url (post-redirect) not request URL."""

    @staticmethod
    def _patch_transport(handler):
        transport = httpx.MockTransport(handler)
        return patch(
            "plugins.ingest_website.crawler.httpx.AsyncClient",
            return_value=httpx.AsyncClient(transport=transport, follow_redirects=True),
        )

    async def test_records_redirect_url(self):
        """When a page redirects, the final URL (post-redirect) is recorded."""
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/old-page" in url:
                # Simulate redirect: /old-page -> 302 -> /new-page
                return httpx.Response(
                    302,
                    headers={"location": "https://example.com/new-page"},
                    request=request,
                )
            if "/new-page" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text=_html_page("Redirected", "Content after redirect."),
                    request=request,
                )
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=_html_page("Home", "Home content.", ["https://example.com/old-page"]),
                request=request,
            )

        with self._patch_transport(handler):
            results = await crawl("https://example.com", page_limit=10)

        urls = [r["url"] for r in results]
        # The redirected page should be recorded under its final URL
        assert "https://example.com/new-page" in urls
        # The original /old-page should NOT appear as a recorded URL
        assert "https://example.com/old-page" not in urls


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

        with patch("plugins.ingest_website.plugin.crawl", return_value=mock_pages):
            result = await plugin.handle(event)
        assert isinstance(result, IngestWebsiteResult)
        # delete_collection is no longer called — incremental dedup replaces it
        assert plugin._knowledge_store.deleted == []
        assert "example.com-knowledge" in plugin._knowledge_store.collections
        # Identification fields must be propagated from the request event
        # so the alkemio-server result handler can correlate the result
        # back to the persona.
        assert result.persona_id == event.persona_id
        assert result.type == event.type
        assert result.purpose == event.purpose

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
        # Cleanup-only path must still propagate identification fields.
        assert result.persona_id == event.persona_id
        assert result.type == event.type
        assert result.purpose == event.purpose

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
        """When crawl raises CrawlError, return failure without running cleanup."""
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
            side_effect=CrawlError("Failed to reach base URL https://example.com/: Connection refused"),
        ):
            result = await plugin.handle(event)

        assert result.result == "failure"
        assert "Failed to reach base URL" in result.error
        # Store should be untouched — no cleanup ran
        assert len(store.collections[collection]) == 1

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()


class TestIngestWebsiteSummarizationBehavior:
    """Verify summarization step inclusion based on summarize_enabled and concurrency."""

    _MOCK_PAGES = [{"url": "https://example.com", "html": "<p>Content for ingestion test.</p>"}]

    async def test_summarize_enabled_with_concurrency(self):
        """When summarize_enabled=True and concurrency>0, summary steps are included."""
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            summarize_enabled=True,
            summarize_concurrency=8,
        )
        event = make_ingest_website()

        with patch("plugins.ingest_website.plugin.crawl", return_value=self._MOCK_PAGES), \
             patch("plugins.ingest_website.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = AsyncMock(
                return_value=MagicMock(success=True, errors=[])
            )
            await plugin.handle(event)

        # Inspect the steps passed to IngestEngine
        call_kwargs = mock_engine.call_args
        batch_steps = call_kwargs.kwargs["batch_steps"]
        finalize_steps = call_kwargs.kwargs["finalize_steps"]
        batch_names = [type(s).__name__ for s in batch_steps]
        finalize_names = [type(s).__name__ for s in finalize_steps]
        assert "DocumentSummaryStep" in batch_names
        assert "BodyOfKnowledgeSummaryStep" in finalize_names

    async def test_summarize_enabled_with_zero_concurrency(self):
        """When summarize_enabled=True and concurrency=0, summary steps included with concurrency=1."""
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            summarize_enabled=True,
            summarize_concurrency=0,
        )
        assert plugin._summarize_concurrency == 1  # 0 maps to 1

        event = make_ingest_website()

        with patch("plugins.ingest_website.plugin.crawl", return_value=self._MOCK_PAGES), \
             patch("plugins.ingest_website.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = AsyncMock(
                return_value=MagicMock(success=True, errors=[])
            )
            await plugin.handle(event)

        call_kwargs = mock_engine.call_args
        batch_names = [type(s).__name__ for s in call_kwargs.kwargs["batch_steps"]]
        finalize_names = [type(s).__name__ for s in call_kwargs.kwargs["finalize_steps"]]
        assert "DocumentSummaryStep" in batch_names
        assert "BodyOfKnowledgeSummaryStep" in finalize_names

    async def test_summarize_disabled(self):
        """When summarize_enabled=False, no summary steps are included."""
        plugin = IngestWebsitePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            summarize_enabled=False,
            summarize_concurrency=8,
        )
        event = make_ingest_website()

        with patch("plugins.ingest_website.plugin.crawl", return_value=self._MOCK_PAGES), \
             patch("plugins.ingest_website.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = AsyncMock(
                return_value=MagicMock(success=True, errors=[])
            )
            await plugin.handle(event)

        call_kwargs = mock_engine.call_args
        batch_names = [type(s).__name__ for s in call_kwargs.kwargs["batch_steps"]]
        finalize_names = [type(s).__name__ for s in call_kwargs.kwargs["finalize_steps"]]
        assert "DocumentSummaryStep" not in batch_names
        assert "BodyOfKnowledgeSummaryStep" not in finalize_names
