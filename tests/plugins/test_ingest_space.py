"""Unit tests for IngestSpacePlugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
            "collaboration": {"callouts": []},
            "subspaces": [],
        }
        documents = []
        _process_space(space, documents, depth=0)
        assert len(documents) == 1
        assert "Test Space" in documents[0].content

    def test_process_callouts(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "S", "description": "D"},
            "collaboration": {
                "callouts": [{
                    "id": "callout-1",
                    "type": "POST",
                    "framing": {"profile": {"displayName": "C", "description": "Callout desc"}},
                    "contributions": [{
                        "post": {"id": "post-1", "profile": {"displayName": "P", "description": "Post content"}},
                    }],
                }],
            },
            "subspaces": [],
        }
        documents = []
        _process_space(space, documents, depth=0)
        # Space + callout + post = 3
        assert len(documents) == 3

    def test_recursive_subspaces(self):
        space = {
            "id": "space-1",
            "profile": {"displayName": "Root", "description": "Root desc"},
            "collaboration": {"callouts": []},
            "subspaces": [{
                "id": "sub-1",
                "profile": {"displayName": "Sub", "description": "Sub desc"},
                "collaboration": {"callouts": []},
                "subspaces": [],
            }],
        }
        documents = []
        _process_space(space, documents, depth=0)
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

    async def test_empty_corpus_cleanup_deletes_stale_chunks(self):
        """When fetch returns empty, cleanup pipeline removes all stored chunks."""
        store = MockKnowledgeStorePort()
        collection = "bok-123-knowledge"

        # Pre-populate the store with existing chunks
        await store.ingest(
            collection=collection,
            documents=["old content 1", "old content 2"],
            metadatas=[
                {"documentId": "doc-1", "embeddingType": "chunk", "source": "s", "type": "t", "title": "t1"},
                {"documentId": "doc-1", "embeddingType": "chunk", "source": "s", "type": "t", "title": "t2"},
            ],
            ids=["hash-aaa", "hash-bbb"],
            embeddings=[[0.1] * 384, [0.2] * 384],
        )
        assert len(store.collections[collection]) == 2

        graphql_client = AsyncMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
            graphql_client=graphql_client,
        )

        event = make_ingest_body_of_knowledge()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            return_value=[],
        ):
            result = await plugin.handle(event)

        assert isinstance(result, IngestBodyOfKnowledgeResult)
        assert result.result == "success"
        # All previously stored chunks should be deleted
        assert len(store.collections.get(collection, [])) == 0

    async def test_fetch_failure_preserves_collection(self):
        """When fetch raises an exception, chunks are preserved and result is failure."""
        store = MockKnowledgeStorePort()
        collection = "bok-123-knowledge"

        # Pre-populate the store
        await store.ingest(
            collection=collection,
            documents=["existing content"],
            metadatas=[
                {"documentId": "doc-1", "embeddingType": "chunk", "source": "s", "type": "t", "title": "t"},
            ],
            ids=["hash-ccc"],
            embeddings=[[0.1] * 384],
        )

        graphql_client = AsyncMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
            graphql_client=graphql_client,
        )

        event = make_ingest_body_of_knowledge()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            side_effect=RuntimeError("GraphQL connection failed"),
        ):
            result = await plugin.handle(event)

        assert result.result == "failure"
        assert result.error is not None
        # Chunks should NOT be deleted on failure
        assert len(store.collections[collection]) == 1
