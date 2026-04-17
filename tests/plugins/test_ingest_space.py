"""Unit tests for IngestSpacePlugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.events.ingest_space import IngestBodyOfKnowledgeResult
from plugins.ingest_space.file_parsers import parse_file
from plugins.ingest_space.plugin import IngestSpacePlugin
from plugins.ingest_space.space_reader import _process_space
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


class TestSpaceReader:
    def test_process_space_extracts_description(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "Test Space", "description": "A test space"},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        documents = []
        _process_space(space, documents, set(), depth=0)
        assert len(documents) == 1
        assert "Test Space" in documents[0].content

    def test_process_callouts(self):
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
        _process_space(space, documents, set(), depth=0)
        # Space + callout + post = 3
        assert len(documents) == 3

    def test_recursive_subspaces(self):
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
        _process_space(space, documents, set(), depth=0)
        assert len(documents) == 2  # Root + subspace

    # ------------------------------------------------------------------
    # Callout context enrichment
    # ------------------------------------------------------------------

    def test_callout_context_prepended_to_post(self):
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
        _process_space(space, documents, set(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        # Context comes before post content
        assert post_doc.content.startswith("Topic A")
        assert "About topic A" in post_doc.content
        assert "Post body here" in post_doc.content
        # Callout context appears before the post body
        ctx_end = post_doc.content.index("About topic A")
        body_start = post_doc.content.index("Post body here")
        assert ctx_end < body_start

    def test_callout_context_prepended_to_whiteboard(self):
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
        _process_space(space, documents, set(), depth=0)
        wb_doc = next(d for d in documents if d.metadata.document_id == "wb-1")
        assert wb_doc.content.startswith("Topic B")
        assert "About topic B" in wb_doc.content
        assert "whiteboard data" in wb_doc.content

    def test_callout_context_prepended_to_link(self):
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
        _process_space(space, documents, set(), depth=0)
        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        assert link_doc.content.startswith("Resources")
        assert "Useful links" in link_doc.content
        assert "Example" in link_doc.content
        assert "https://example.com" in link_doc.content

    def test_callout_context_with_empty_description(self):
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
        _process_space(space, documents, set(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        # Context is just the name (no description separator)
        assert post_doc.content.startswith("Just Name")
        assert "Body" in post_doc.content

    def test_callout_description_truncated_at_400_chars(self):
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
        _process_space(space, documents, set(), depth=0)
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

    def test_space_uri_propagated(self):
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
        _process_space(space, documents, set(), depth=0)
        assert documents[0].metadata.uri == "https://app.alkemio.org/space-1"

    def test_post_uri_from_profile_url(self):
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
        _process_space(space, documents, set(), depth=0)
        post_doc = next(d for d in documents if d.metadata.document_id == "post-1")
        assert post_doc.metadata.uri == "https://app.alkemio.org/post-1"

    def test_link_uri_prefers_link_uri_over_profile_url(self):
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
        _process_space(space, documents, set(), depth=0)
        link_doc = next(d for d in documents if d.metadata.document_id == "link-1")
        assert link_doc.metadata.uri == "https://external.com"

    def test_empty_url_stored_as_none(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "Desc", "url": ""},
            "collaboration": {"calloutsSet": {"callouts": []}},
            "subspaces": [],
        }
        documents = []
        _process_space(space, documents, set(), depth=0)
        assert documents[0].metadata.uri is None

    def test_callout_uri_propagated(self):
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
        _process_space(space, documents, set(), depth=0)
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
            import asyncio
            mock_engine.return_value.run = lambda *a, **kw: asyncio.coroutine(
                lambda: MagicMock(success=True, errors=[])
            )()
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
