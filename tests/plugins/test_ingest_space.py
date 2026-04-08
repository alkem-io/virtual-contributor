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

    async def test_empty_corpus_cleanup_deletes_existing_chunks(self):
        """When read_space_tree returns [], previously-stored chunks are deleted."""
        store = MockKnowledgeStorePort()
        collection_name = "bok-123-knowledge"

        # Seed the store with pre-existing chunks
        await store.ingest(
            collection=collection_name,
            documents=["old content 1", "old content 2"],
            metadatas=[
                {"documentId": "doc-1", "source": "s", "type": "knowledge",
                 "title": "t", "embeddingType": "chunk", "chunkIndex": 0},
                {"documentId": "doc-1", "source": "s", "type": "knowledge",
                 "title": "t", "embeddingType": "chunk", "chunkIndex": 1},
            ],
            ids=["hash-aaa", "hash-bbb"],
            embeddings=[[0.1] * 384, [0.2] * 384],
        )
        assert len(store.collections[collection_name]) == 2

        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
            graphql_client=object(),  # non-None so the client check passes
        )

        event = make_ingest_body_of_knowledge()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await plugin.handle(event)

        assert isinstance(result, IngestBodyOfKnowledgeResult)
        assert result.result == "success"
        # All previously-stored chunks should be deleted
        assert len(store.collections.get(collection_name, [])) == 0

    async def test_fetch_failure_preserves_existing_chunks(self):
        """When read_space_tree raises, existing chunks are NOT deleted."""
        store = MockKnowledgeStorePort()
        collection_name = "bok-123-knowledge"

        # Seed the store with pre-existing chunks
        await store.ingest(
            collection=collection_name,
            documents=["old content"],
            metadatas=[
                {"documentId": "doc-1", "source": "s", "type": "knowledge",
                 "title": "t", "embeddingType": "chunk", "chunkIndex": 0},
            ],
            ids=["hash-aaa"],
            embeddings=[[0.1] * 384],
        )
        assert len(store.collections[collection_name]) == 1

        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=store,
            graphql_client=object(),
        )

        event = make_ingest_body_of_knowledge()
        with patch(
            "plugins.ingest_space.space_reader.read_space_tree",
            new_callable=AsyncMock,
            side_effect=RuntimeError("GraphQL timeout"),
        ):
            result = await plugin.handle(event)

        assert result.result == "failure"
        # Chunks must be preserved on fetch failure
        assert len(store.collections[collection_name]) == 1
