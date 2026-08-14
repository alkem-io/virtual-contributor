"""Unit tests for IngestSpacePlugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.ingest_pipeline import DocumentType
from core.events.ingest_space import IngestBodyOfKnowledgeResult
from plugins.ingest_space.file_parsers import parse_file
from plugins.ingest_space.plugin import IngestSpacePlugin
from plugins.ingest_space.space_reader import (
    BOK_TYPE_KNOWLEDGE_BASE,
    BOK_TYPE_SPACE,
    _process_space,
    read_body_of_knowledge,
    read_knowledge_base_tree,
)
from tests.conftest import (
    MockEmbeddingsPort,
    MockKnowledgeStorePort,
    MockLLMPort,
    make_ingest_body_of_knowledge,
)


class TestFileParsers:
    def test_unsupported_format_returns_none(self):
        assert parse_file(b"data", "file.unknown") is None

    def test_pdf_parsing(self):
        # Create a minimal PDF to test (skip if pypdf can't handle it)
        result = parse_file(b"%PDF-1.4 invalid", "test.pdf")
        # May return None for invalid PDF, which is fine
        assert result is None or isinstance(result, str)


def _mock_graphql_client():
    """Create an AsyncMock graphql_client with fetch_url returning None."""
    client = AsyncMock()
    client.fetch_url = AsyncMock(return_value=None)
    return client


def _default_stats():
    return {"fetched": 0, "skipped": 0}


class TestSpaceReader:
    async def test_process_space_extracts_description(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "Test Space", "description": "A test space"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        assert len(documents) == 1
        assert "Test Space" in documents[0].content

    async def test_process_callouts(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "D"},
            "collaboration": {
                "calloutsSet": {"callouts": [{
                    "id": "callout-1",
                    "type": "POST",
                    "framing": {"profile": {"displayName": "C", "description": "Callout desc"}},
                    "contributions": [{
                        "post": {"id": "post-1", "profile": {"displayName": "P", "description": "Post content"}},
                    }],
                }]},
            },
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        # Space + callout + post = 3
        assert len(documents) == 3

    async def test_recursive_subspaces(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "Root", "description": "Root desc"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [{
                "id": "sub-1",
                "profile": {"displayName": "Sub", "description": "Sub desc"},
                "collaboration": {"calloutsSet": {"callouts": []}},
                "subspaces": [],
            }],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        assert len(documents) == 2  # Root + subspace

    # ------------------------------------------------------------------
    # Callout context enrichment
    # ------------------------------------------------------------------

    async def test_callout_context_prepended_to_post(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "Topic A",
                    "description": "About topic A",
                }},
                "contributions": [{
                    "post": {
                        "id": "post-1",
                        "profile": {
                            "displayName": "My Post",
                            "description": "Post body here",
                        },
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        # Context comes before post content
        assert post_doc.content.startswith("Topic A")
        assert "About topic A" in post_doc.content
        assert "Post body here" in post_doc.content
        # Callout context appears before the post body
        ctx_end = post_doc.content.index("About topic A")
        body_start = post_doc.content.index("Post body here")
        assert ctx_end < body_start

    async def test_callout_context_prepended_to_whiteboard(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "Topic B",
                    "description": "About topic B",
                }},
                "contributions": [{
                    "whiteboard": {
                        "id": "wb-1",
                        "profile": {"displayName": "Board Title"},
                        "content": "whiteboard data",
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        wb_doc = next(d for d in documents if d.metadata.document_id == "wb-1")
        assert wb_doc.content.startswith("Topic B")
        assert "About topic B" in wb_doc.content
        assert "whiteboard data" in wb_doc.content

    async def test_callout_context_prepended_to_link(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "Resources",
                    "description": "Useful links",
                }},
                "contributions": [{
                    "link": {
                        "id": "link-1",
                        "uri": "https://example.com",
                        "profile": {
                            "displayName": "Example",
                            "description": "An example site",
                        },
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        assert link_doc.content.startswith("Resources")
        assert "Useful links" in link_doc.content
        assert "Example" in link_doc.content
        assert "https://example.com" in link_doc.content

    async def test_callout_context_with_empty_description(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "Just Name",
                    "description": "",
                }},
                "contributions": [{
                    "post": {
                        "id": "post-1",
                        "profile": {"displayName": "P", "description": "Body"},
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        # Context is just the name (no description separator)
        assert post_doc.content.startswith("Just Name")
        assert "Body" in post_doc.content

    async def test_callout_description_truncated_at_400_chars(self):
        long_desc = "A" * 600  # plain text, no HTML
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "Co",
                    "description": long_desc,
                }},
                "contributions": [{
                    "post": {
                        "id": "post-1",
                        "profile": {"displayName": "P", "description": "Body"},
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        # The callout context should contain at most 400 chars of description
        # Split on the post title marker to isolate the context prefix
        before_post = post_doc.content.split("# P")[0]
        # The 400-char truncated portion must be present but the full 600 must not
        assert "A" * 400 in before_post
        assert "A" * 401 not in before_post

    # ------------------------------------------------------------------
    # URI propagation
    # ------------------------------------------------------------------

    async def test_space_uri_propagated(self):
        space = {
            "id": "space-1",
            "profile": {
                "displayName": "S",
                "description": "Desc",
                "url": "https://app.alkemio.org/space-1",
            },
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        assert documents[0].metadata.uri == "https://app.alkemio.org/space-1"

    async def test_post_uri_from_profile_url(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {"displayName": "C", "description": ""}},
                "contributions": [{
                    "post": {
                        "id": "post-1",
                        "profile": {
                            "displayName": "P",
                            "description": "Body",
                            "url": "https://app.alkemio.org/post-1",
                        },
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        assert post_doc.metadata.uri == "https://app.alkemio.org/post-1"

    async def test_link_uri_prefers_link_uri_over_profile_url(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {"displayName": "C", "description": ""}},
                "contributions": [{
                    "link": {
                        "id": "link-1",
                        "uri": "https://external.com",
                        "profile": {
                            "displayName": "Link Title",
                            "description": "Link desc",
                            "url": "https://app.alkemio.org/link-1",
                        },
                    },
                }],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        assert link_doc.metadata.uri == "https://external.com"

    async def test_empty_url_stored_as_none(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc", "url": ""},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        assert documents[0].metadata.uri is None

    async def test_callout_uri_propagated(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "C",
                    "description": "Callout desc",
                    "url": "https://app.alkemio.org/callout-1",
                }},
                "contributions": [],
            }]}},
            "subspaces": [],
        }
        documents = []
        await _process_space(space, documents, set(), graphql_client=_mock_graphql_client(), stats=_default_stats(), depth=0)
        callout_doc = next(d for d in documents if d.metadata.document_id == "co-1")
        assert callout_doc.metadata.uri == "https://app.alkemio.org/callout-1"


class TestIngestSpacePlugin:
    @pytest.fixture
    def plugin(self):
        return IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
        )

    async def test_missing_graphql_client(self, plugin):
        event = make_ingest_body_of_knowledge()
        result = await plugin.handle(event)
        assert isinstance(result, IngestBodyOfKnowledgeResult)
        assert result.result == "failure"
        assert result.error is not None

    async def test_error_handling(self, plugin):
        event = make_ingest_body_of_knowledge()
        result = await plugin.handle(event)
        assert result.result == "failure"

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()

    async def test_empty_space_runs_cleanup(self):
        """When read_space_tree returns [], cleanup deletes pre-existing chunks."""
        store = MockKnowledgeStorePort()
        # Pre-populate the store with chunks that should be cleaned up
        collection = "bok-123-knowledge"
        await store.ingest(
            collection=collection,
            documents=["old content"],
            metadatas=[{"documentId": "old-doc", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["old-hash-1"],
            embeddings=[[0.1] * 384],
        )
        assert len(store.collections[collection]) == 1

        mock_graphql = AsyncMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
            graphql_client=mock_graphql,
        )

        event = make_ingest_body_of_knowledge()
        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=[]):
            result = await plugin.handle(event)

        assert isinstance(result, IngestBodyOfKnowledgeResult)
        assert result.result == "success"
        # All pre-existing chunks should have been deleted
        assert len(store.collections.get(collection, [])) == 0

    async def test_empty_space_returns_success(self):
        """Empty-but-successful fetch returns result='success'."""
        mock_graphql = AsyncMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=mock_graphql,
        )

        event = make_ingest_body_of_knowledge()
        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=[]):
            result = await plugin.handle(event)

        assert result.result == "success"
        assert result.error is None

    async def test_fetch_failure_no_cleanup(self):
        """When read_space_tree raises, return failure without running cleanup."""
        store = MockKnowledgeStorePort()
        collection = "bok-123-knowledge"
        await store.ingest(
            collection=collection,
            documents=["preserved content"],
            metadatas=[{"documentId": "doc-1", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["hash-1"],
            embeddings=[[0.1] * 384],
        )

        mock_graphql = AsyncMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
            graphql_client=mock_graphql,
        )

        event = make_ingest_body_of_knowledge()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            side_effect=RuntimeError("GraphQL connection failed"),
        ):
            result = await plugin.handle(event)

        assert result.result == "failure"
        assert result.error is not None
        # Store should be untouched — no cleanup ran
        assert len(store.collections[collection]) == 1


class TestIngestSpaceSummarizationBehavior:
    """Verify summarization step inclusion based on summarize_enabled and concurrency."""

    async def _run_with_mock_graphql(self, plugin):
        """Helper to run plugin with a mocked graphql client and space reader."""
        from core.domain.ingest_pipeline import Document, DocumentMetadata

        mock_docs = [
            Document(
                content="Test space content for summarization.",
                metadata=DocumentMetadata(
                    document_id="space-1",
                    source="graphql",
                    type="knowledge",
                    title="Test Space",
                ),
            ),
        ]
        event = make_ingest_body_of_knowledge()

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=mock_docs), \
             patch("plugins.ingest_space.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = AsyncMock(
                return_value=MagicMock(success=True, errors=[])
            )
            await plugin.handle(event)

        return mock_engine

    async def test_summarize_enabled_with_concurrency(self):
        """When summarize_enabled=True and concurrency>0, summary steps are included."""
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=MagicMock(),
            summarize_enabled=True,
            summarize_concurrency=8,
        )
        mock_engine = await self._run_with_mock_graphql(plugin)

        call_kwargs = mock_engine.call_args
        batch_names = [type(s).__name__ for s in call_kwargs.kwargs["batch_steps"]]
        finalize_names = [type(s).__name__ for s in call_kwargs.kwargs["finalize_steps"]]
        assert "DocumentSummaryStep" in batch_names
        assert "BodyOfKnowledgeSummaryStep" in finalize_names

    async def test_summarize_enabled_with_zero_concurrency(self):
        """When summarize_enabled=True and concurrency=0, summary steps included with concurrency=1."""
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=MagicMock(),
            summarize_enabled=True,
            summarize_concurrency=0,
        )
        assert plugin._summarize_concurrency == 1  # 0 maps to 1

        mock_engine = await self._run_with_mock_graphql(plugin)

        call_kwargs = mock_engine.call_args
        batch_names = [type(s).__name__ for s in call_kwargs.kwargs["batch_steps"]]
        finalize_names = [type(s).__name__ for s in call_kwargs.kwargs["finalize_steps"]]
        assert "DocumentSummaryStep" in batch_names
        assert "BodyOfKnowledgeSummaryStep" in finalize_names

    async def test_summarize_disabled(self):
        """When summarize_enabled=False, no summary steps are included."""
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=MagicMock(),
            summarize_enabled=False,
            summarize_concurrency=8,
        )
        mock_engine = await self._run_with_mock_graphql(plugin)

        call_kwargs = mock_engine.call_args
        batch_names = [type(s).__name__ for s in call_kwargs.kwargs["batch_steps"]]
        finalize_names = [type(s).__name__ for s in call_kwargs.kwargs["finalize_steps"]]
        assert "DocumentSummaryStep" not in batch_names
        assert "BodyOfKnowledgeSummaryStep" not in finalize_names


class TestLinkFetching:
    """Tests for link contribution body fetching in _process_space."""

    def _link_space(self, link_uri="https://example.com/doc.pdf"):
        """Build a minimal space dict with a single link contribution."""
        return {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "Resources",
                    "description": "Useful resources",
                }},
                "contributions": [{
                    "link": {
                        "id": "link-1",
                        "uri": link_uri,
                        "profile": {
                            "displayName": "My Document",
                            "description": "A document about things",
                        },
                    },
                }],
            }]}},
            "subspaces": [],
        }

    async def test_link_with_successful_fetch(self):
        """When fetch_url succeeds and extract_text returns content, the
        document body contains the extracted text instead of just URL metadata."""
        gc = _mock_graphql_client()
        gc.fetch_url = AsyncMock(return_value=(b"pdf bytes", "application/pdf"))
        stats = _default_stats()

        with patch(
            "plugins.ingest_space.space_reader.extract_text",
            return_value="Extracted PDF content here",
        ):
            documents = []
            await _process_space(
                self._link_space(), documents, set(),
                graphql_client=gc, stats=stats, depth=0,
            )

        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        assert "Extracted PDF content here" in link_doc.content
        # The title header should still be present
        assert "My Document" in link_doc.content
        # Callout context should NOT be prepended when we have real content
        assert not link_doc.content.startswith("Resources")
        assert stats["fetched"] == 1
        assert stats["skipped"] == 0

    async def test_link_with_failed_fetch(self):
        """When fetch_url returns None, fallback to metadata (callout context
        + title + URL)."""
        gc = _mock_graphql_client()
        gc.fetch_url = AsyncMock(return_value=None)
        stats = _default_stats()

        documents = []
        await _process_space(
            self._link_space(), documents, set(),
            graphql_client=gc, stats=stats, depth=0,
        )

        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        # Fallback: callout context is prepended
        assert link_doc.content.startswith("Resources")
        assert "Useful resources" in link_doc.content
        assert "My Document" in link_doc.content
        assert "https://example.com/doc.pdf" in link_doc.content
        assert stats["skipped"] == 1
        assert stats["fetched"] == 0

    async def test_link_with_unsupported_format(self):
        """When fetch succeeds but extract_text returns None (unsupported
        format), fallback to metadata."""
        gc = _mock_graphql_client()
        gc.fetch_url = AsyncMock(return_value=(b"\x00\x01binary", "application/octet-stream"))
        stats = _default_stats()

        with patch(
            "plugins.ingest_space.space_reader.extract_text",
            return_value=None,
        ):
            documents = []
            await _process_space(
                self._link_space(), documents, set(),
                graphql_client=gc, stats=stats, depth=0,
            )

        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        # Fallback path: callout context + URL metadata
        assert link_doc.content.startswith("Resources")
        assert "https://example.com/doc.pdf" in link_doc.content
        assert stats["skipped"] == 1
        assert stats["fetched"] == 0

    async def test_stats_tracking_multiple_links(self):
        """Stats correctly count fetched and skipped across multiple links."""
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc"},
            "collaboration": {"calloutsSet": {"callouts": [{
                "id": "co-1",
                "framing": {"profile": {"displayName": "Links", "description": ""}},
                "contributions": [
                    {
                        "link": {
                            "id": "link-ok",
                            "uri": "https://example.com/good.pdf",
                            "profile": {"displayName": "Good", "description": "A good doc"},
                        },
                    },
                    {
                        "link": {
                            "id": "link-fail",
                            "uri": "https://example.com/bad",
                            "profile": {"displayName": "Bad", "description": "A bad link"},
                        },
                    },
                ],
            }]}},
            "subspaces": [],
        }

        call_count = 0

        async def side_effect(url):
            nonlocal call_count
            call_count += 1
            if "good" in url:
                return (b"pdf data", "application/pdf")
            return None

        gc = _mock_graphql_client()
        gc.fetch_url = AsyncMock(side_effect=side_effect)
        stats = _default_stats()

        with patch(
            "plugins.ingest_space.space_reader.extract_text",
            return_value="Extracted text",
        ):
            documents = []
            await _process_space(
                space, documents, set(),
                graphql_client=gc, stats=stats, depth=0,
            )

        assert stats["fetched"] == 1
        assert stats["skipped"] == 1


class TestKnowledgeBaseReader:
    """Tests for read_knowledge_base_tree — the alkemio-knowledge-base path."""

    def _kb_payload(self, *, with_callout: bool = True):
        callouts = []
        if with_callout:
            callouts.append({
                "id": "co-1",
                "framing": {"profile": {
                    "displayName": "KB Callout",
                    "description": "Callout desc",
                }},
                "contributions": [{
                    "post": {
                        "id": "post-1",
                        "profile": {
                            "displayName": "P",
                            "description": "Post body",
                        },
                    },
                }],
            })
        return {
            "lookup": {
                "knowledgeBase": {
                    "id": "kb-1",
                    "profile": {
                        "displayName": "KB Root",
                        "description": "Root description",
                    },
                    "calloutsSet": {"callouts": callouts},
                },
            },
        }

    async def test_walks_callouts(self):
        gc = _mock_graphql_client()
        gc.query = AsyncMock(return_value=self._kb_payload())
        documents = await read_knowledge_base_tree(gc, "kb-1")
        # KB root + callout + post
        ids = {d.metadata.document_id for d in documents}
        assert "kb-1" in ids
        assert "co-1" in ids
        assert "post-1" in ids

    async def test_top_doc_type_is_knowledge(self):
        gc = _mock_graphql_client()
        gc.query = AsyncMock(return_value=self._kb_payload(with_callout=False))
        documents = await read_knowledge_base_tree(gc, "kb-1")
        root = next(d for d in documents if d.metadata.document_id == "kb-1")
        assert root.metadata.type == DocumentType.KNOWLEDGE.value

    async def test_empty_knowledge_base_returns_empty_list(self):
        gc = _mock_graphql_client()
        gc.query = AsyncMock(return_value={"lookup": {"knowledgeBase": None}})
        documents = await read_knowledge_base_tree(gc, "kb-missing")
        assert documents == []

    async def test_issues_knowledge_base_query(self):
        """Ensure we call lookup.knowledgeBase(), not lookup.space()."""
        gc = _mock_graphql_client()
        gc.query = AsyncMock(return_value={"lookup": {"knowledgeBase": None}})
        await read_knowledge_base_tree(gc, "kb-1")
        # Inspect the GraphQL query string passed to the client
        call_args = gc.query.call_args
        query_str = call_args.args[0]
        variables = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("variables", {})
        assert "knowledgeBase(ID:" in query_str
        assert "space(ID:" not in query_str
        assert variables == {"kbId": "kb-1"}


class TestBodyOfKnowledgeDispatcher:
    """Tests for the read_body_of_knowledge type-routing dispatcher."""

    async def test_routes_alkemio_space_to_space_reader(self):
        gc = MagicMock()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new=AsyncMock(return_value=[]),
        ) as space_mock, patch(
            "plugins.ingest_space.space_reader.read_knowledge_base_tree",
            new=AsyncMock(return_value=[]),
        ) as kb_mock:
            await read_body_of_knowledge(gc, "bok-1", BOK_TYPE_SPACE)
        space_mock.assert_awaited_once_with(gc, "bok-1")
        kb_mock.assert_not_awaited()

    async def test_routes_alkemio_knowledge_base_to_kb_reader(self):
        gc = MagicMock()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new=AsyncMock(return_value=[]),
        ) as space_mock, patch(
            "plugins.ingest_space.space_reader.read_knowledge_base_tree",
            new=AsyncMock(return_value=[]),
        ) as kb_mock:
            await read_body_of_knowledge(gc, "bok-1", BOK_TYPE_KNOWLEDGE_BASE)
        kb_mock.assert_awaited_once_with(gc, "bok-1")
        space_mock.assert_not_awaited()

    async def test_unknown_type_defaults_to_space_reader(self):
        """Unknown bok_type strings fall back to the space path (dominant case)."""
        gc = MagicMock()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new=AsyncMock(return_value=[]),
        ) as space_mock, patch(
            "plugins.ingest_space.space_reader.read_knowledge_base_tree",
            new=AsyncMock(return_value=[]),
        ) as kb_mock:
            await read_body_of_knowledge(gc, "bok-1", "something-unexpected")
        space_mock.assert_awaited_once_with(gc, "bok-1")
        kb_mock.assert_not_awaited()


class TestIngestSpacePluginDispatchesOnType:
    """The plugin must pass event.type through to the dispatcher."""

    async def test_plugin_uses_knowledge_base_reader_for_alkemio_knowledge_base(self):
        store = MockKnowledgeStorePort()
        llm = MockLLMPort()
        embeddings = MockEmbeddingsPort()
        plugin = IngestSpacePlugin(
            llm=llm,
            embeddings=embeddings,
            knowledge_store=store,
            graphql_client=AsyncMock(),
        )
        event = make_ingest_body_of_knowledge(type=BOK_TYPE_KNOWLEDGE_BASE)
        with patch(
            "plugins.ingest_space.space_reader.read_knowledge_base_tree",
            new=AsyncMock(return_value=[]),
        ) as kb_mock, patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new=AsyncMock(return_value=[]),
        ) as space_mock:
            result = await plugin.handle(event)

        assert result.result == "success"
        kb_mock.assert_awaited_once()
        space_mock.assert_not_awaited()
        # Zero-document cleanup branch: no LLM/embeddings work,
        # and no collection-level deletion either.
        assert llm.calls == []
        assert embeddings.calls == []
        assert embeddings.query_calls == []
        assert store.deleted == []

    async def test_plugin_uses_space_reader_for_alkemio_space(self):
        store = MockKnowledgeStorePort()
        llm = MockLLMPort()
        embeddings = MockEmbeddingsPort()
        plugin = IngestSpacePlugin(
            llm=llm,
            embeddings=embeddings,
            knowledge_store=store,
            graphql_client=AsyncMock(),
        )
        event = make_ingest_body_of_knowledge(type=BOK_TYPE_SPACE)
        with patch(
            "plugins.ingest_space.space_reader.read_knowledge_base_tree",
            new=AsyncMock(return_value=[]),
        ) as kb_mock, patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new=AsyncMock(return_value=[]),
        ) as space_mock:
            result = await plugin.handle(event)

        assert result.result == "success"
        space_mock.assert_awaited_once()
        kb_mock.assert_not_awaited()
        # Zero-document cleanup branch: no LLM/embeddings work,
        # and no collection-level deletion either.
        assert llm.calls == []
        assert embeddings.calls == []
        assert embeddings.query_calls == []
        assert store.deleted == []


def _nested_space_fixture() -> dict:
    """A space tree covering every level and every contribution kind.

    root (sp-1)
      ├── callout co-root
      ├── L1 subspace sub-1
      │     └── callout co-l1  ── post / whiteboard / link
      └── L2 subspace sub-2 (nested under sub-1)
            └── callout co-l2
    """
    return {
        "id": "sp-1",
        "profile": {
            "displayName": "Root Space",
            "description": "The root description",
            "url": "https://example.test/sp-1",
        },
        "collaboration": {"calloutsSet": {"callouts": [
            {
                "id": "co-root",
                "framing": {"profile": {
                    "displayName": "Root Callout",
                    "description": "Root callout description",
                }},
                "contributions": [],
            },
        ]}},
        "subspaces": [
            {
                "id": "sub-1",
                "profile": {
                    "displayName": "First Level",
                    "description": "L1 description",
                },
                "collaboration": {"calloutsSet": {"callouts": [
                    {
                        "id": "co-l1",
                        "framing": {"profile": {
                            "displayName": "L1 Callout",
                            "description": "L1 callout description",
                        }},
                        "contributions": [
                            {"post": {
                                "id": "post-1",
                                "profile": {
                                    "displayName": "A Post",
                                    "description": "Post body text",
                                },
                            }},
                            {"whiteboard": {
                                "id": "wb-1",
                                "content": "Whiteboard scene text",
                                "profile": {"displayName": "A Whiteboard"},
                            }},
                            {"link": {
                                "id": "link-1",
                                "uri": "https://example.test/doc",
                                "profile": {
                                    "displayName": "A Link",
                                    "description": "Link description",
                                },
                            }},
                        ],
                    },
                ]}},
                "subspaces": [
                    {
                        "id": "sub-2",
                        "profile": {
                            "displayName": "Second Level",
                            "description": "L2 description",
                        },
                        "collaboration": {"calloutsSet": {"callouts": [
                            {
                                "id": "co-l2",
                                "framing": {"profile": {
                                    "displayName": "L2 Callout",
                                    "description": "L2 callout description",
                                }},
                                "contributions": [],
                            },
                        ]}},
                        "subspaces": [],
                    },
                ],
            },
        ],
    }


async def _walk(space: dict, **kwargs) -> dict:
    """Run the reader and index the emitted documents by document_id."""
    documents: list = []
    await _process_space(
        space, documents, set(),
        graphql_client=_mock_graphql_client(),
        stats=_default_stats(), depth=0, **kwargs,
    )
    return {d.metadata.document_id: d.metadata for d in documents}


class TestHierarchyPosition:
    """Every emitted document records where in the tree it came from."""

    async def test_full_tree_positions(self):
        by_id = await _walk(_nested_space_fixture())

        # Expected (space_id, subspace_id, callout_id, depth) per document.
        expected = {
            "sp-1":     ("sp-1", None,    None,      0),  # root description
            "co-root":  ("sp-1", None,    "co-root", 0),  # callout keeps owner tier
            "sub-1":    ("sp-1", "sub-1", None,      1),
            "co-l1":    ("sp-1", "sub-1", "co-l1",   1),
            "post-1":   ("sp-1", "sub-1", "co-l1",   3),
            "wb-1":     ("sp-1", "sub-1", "co-l1",   3),
            "link-1":   ("sp-1", "sub-1", "co-l1",   3),
            "sub-2":    ("sp-1", "sub-2", None,      2),  # nearest subspace is itself
            "co-l2":    ("sp-1", "sub-2", "co-l2",   2),
        }
        assert set(by_id) == set(expected)
        for doc_id, (space_id, subspace_id, callout_id, depth) in expected.items():
            meta = by_id[doc_id]
            assert meta.space_id == space_id, doc_id
            assert meta.subspace_id == subspace_id, doc_id
            assert meta.callout_id == callout_id, doc_id
            assert meta.depth == depth, doc_id

    async def test_space_id_identical_at_every_level(self):
        by_id = await _walk(_nested_space_fixture())
        assert {m.space_id for m in by_id.values()} == {"sp-1"}

    async def test_display_names_recorded(self):
        by_id = await _walk(_nested_space_fixture())
        assert by_id["sp-1"].space_name == "Root Space"
        assert by_id["sub-2"].subspace_name == "Second Level"
        assert by_id["post-1"].space_name == "Root Space"
        assert by_id["post-1"].subspace_name == "First Level"

    async def test_position_invariants_hold(self):
        """subspace_id present => depth >= 1; depth 0 => no subspace."""
        by_id = await _walk(_nested_space_fixture())
        for doc_id, meta in by_id.items():
            if meta.subspace_id is not None:
                assert meta.depth >= 1, doc_id
            if meta.depth == 0:
                assert meta.subspace_id is None, doc_id

    async def test_l2_reports_itself_not_its_l1_ancestor(self):
        """The nearest containing subspace wins — not the first-level one."""
        by_id = await _walk(_nested_space_fixture())
        assert by_id["sub-2"].subspace_id == "sub-2"
        assert by_id["co-l2"].subspace_id == "sub-2"

    async def test_blank_name_leaves_name_unknown(self):
        """A known identity with a blank name records the id, not a blank."""
        space = {
            "id": "sp-blank",
            "profile": {"displayName": "", "description": "Has no name"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        assert by_id["sp-blank"].space_id == "sp-blank"
        assert by_id["sp-blank"].space_name is None

    async def test_long_name_capped(self):
        space = {
            "id": "sp-long",
            "profile": {"displayName": "N" * 500, "description": "Long name"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        assert len(by_id["sp-long"].space_name or "") == 200

    async def test_flat_knowledge_base_has_no_subspace(self):
        """The flat case falls out of the depth-0 rule — no special casing."""
        kb_shaped = {
            "id": "kb-1",
            "profile": {"displayName": "A Knowledge Base", "description": "KB"},
            "collaboration": {"calloutsSet": {"callouts": [
                {
                    "id": "co-kb",
                    "framing": {"profile": {
                        "displayName": "KB Callout",
                        "description": "KB callout description",
                    }},
                    "contributions": [
                        {"post": {
                            "id": "kb-post",
                            "profile": {
                                "displayName": "KB Post",
                                "description": "KB post body",
                            },
                        }},
                    ],
                },
            ]}},
            "subspaces": [],
        }
        by_id = await _walk(
            kb_shaped, top_doc_type=DocumentType.KNOWLEDGE.value,
        )
        assert by_id["kb-1"].space_id == "kb-1"
        assert by_id["kb-1"].subspace_id is None
        assert by_id["kb-1"].depth == 0
        assert by_id["co-kb"].callout_id == "co-kb"
        assert by_id["co-kb"].subspace_id is None
        assert by_id["co-kb"].depth == 0
        assert by_id["kb-post"].callout_id == "co-kb"
        assert by_id["kb-post"].depth == 3


class TestMixedCorpusRetrieval:
    """Legacy entries stay retrievable; a positive scope narrows deliberately."""

    async def _seeded_store(self) -> MockKnowledgeStorePort:
        store = MockKnowledgeStorePort()
        await store.ingest(
            collection="c",
            documents=["legacy text", "new text"],
            metadatas=[
                # Ingested before this feature — carries no position at all.
                {"documentId": "old-1", "embeddingType": "chunk"},
                {"documentId": "new-1", "embeddingType": "chunk",
                 "spaceId": "sp-1", "depth": 0},
            ],
            ids=["old-1-0", "new-1-0"],
            embeddings=[[0.1], [0.2]],
        )
        return store

    async def test_unscoped_returns_legacy_and_new(self):
        store = await self._seeded_store()
        result = await store.get(collection="c", include=["metadatas"])
        assert set(result.ids) == {"old-1-0", "new-1-0"}

    async def test_positive_scope_excludes_legacy_entries(self):
        """Documented narrowing: absent keys do not match a positive scope.

        Pinned as an expected decision so consumers (#18/#19) treat a mixed
        corpus as the default state rather than discovering this in production.
        """
        store = await self._seeded_store()
        result = await store.get(
            collection="c", where={"spaceId": "sp-1"}, include=["metadatas"],
        )
        assert result.ids == ["new-1-0"]


class TestNameSanitisationAndTolerantIds:
    """Names are user-controlled and land in a new, filterable metadata key."""

    async def test_pure_markup_name_is_treated_as_unknown(self):
        """No fallback to the raw value — markup must not be stored verbatim."""
        space = {
            "id": "sp-1",
            "profile": {"displayName": "<script>alert(1)</script>",
                        "description": "d"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        assert by_id["sp-1"].space_id == "sp-1"
        assert by_id["sp-1"].space_name is None

    async def test_entity_encoded_markup_does_not_round_trip(self):
        """Decoding must not turn &lt;script&gt; back into live markup."""
        space = {
            "id": "sp-2",
            "profile": {"displayName": "&lt;script&gt;alert(1)&lt;/script&gt;Safe",
                        "description": "d"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        name = by_id["sp-2"].space_name or ""
        assert "<script>" not in name
        assert "</script>" not in name

    async def test_partial_markup_name_keeps_its_text(self):
        space = {
            "id": "sp-3",
            "profile": {"displayName": "<b>Real Name</b>", "description": "d"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        assert by_id["sp-3"].space_name == "Real Name"

    async def test_malformed_callout_is_skipped_not_fatal(self):
        """One malformed node costs its own content, not the whole ingestion.

        The callout has a description, so it reaches document emission — the
        case a shallower fixture would miss. Its healthy sibling must survive
        and no document may be emitted without a stable identity.
        """
        space = {
            "id": "sp-4",
            "profile": {"displayName": "Root", "description": "root text"},
            "collaboration": {"calloutsSet": {"callouts": [
                {"id": None,
                 "framing": {"profile": {"displayName": "bad",
                                         "description": "has a description"}},
                 "contributions": []},
                {"id": "co-ok",
                 "framing": {"profile": {"displayName": "ok",
                                         "description": "healthy callout"}},
                 "contributions": []},
            ]}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        assert set(by_id) == {"sp-4", "co-ok"}
        assert by_id["co-ok"].callout_id == "co-ok"
        assert all(meta.document_id for meta in by_id.values())

    async def test_callout_without_an_id_key_is_skipped(self):
        space = {
            "id": "sp-5",
            "profile": {"displayName": "Root", "description": "root text"},
            "collaboration": {"calloutsSet": {"callouts": [
                {"framing": {"profile": {"displayName": "bad",
                                         "description": "no id key at all"}},
                 "contributions": []},
            ]}},
            "subspaces": [],
        }
        by_id = await _walk(space)
        assert set(by_id) == {"sp-5"}

    async def test_malformed_subspace_is_skipped_with_its_subtree(self):
        space = {
            "id": "sp-6",
            "profile": {"displayName": "Root", "description": "root text"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [
                {"id": None,
                 "profile": {"displayName": "bad", "description": "bad sub"},
                 "collaboration": {"calloutsSet": {"callouts": []}},
                 "subspaces": []},
            ],
        }
        by_id = await _walk(space)
        assert set(by_id) == {"sp-6"}
        assert all(meta.document_id for meta in by_id.values())
