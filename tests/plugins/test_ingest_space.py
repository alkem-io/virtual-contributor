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
