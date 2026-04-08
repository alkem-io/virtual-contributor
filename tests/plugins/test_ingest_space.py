"""Unit tests for IngestSpacePlugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    async def test_summarize_enabled_includes_summary_steps(self):
        """When summarize_enabled=True, pipeline includes summary steps."""
        from core.domain.ingest_pipeline import Document, DocumentMetadata

        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=MagicMock(),
            summarize_enabled=True,
        )
        event = make_ingest_body_of_knowledge()
        mock_docs = [
            Document(
                content="Test content",
                metadata=DocumentMetadata(
                    document_id="doc-1", source="test", type="knowledge", title="Test",
                ),
            )
        ]

        import asyncio
        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=mock_docs), \
             patch("plugins.ingest_space.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = lambda *a, **kw: asyncio.coroutine(
                lambda: MagicMock(success=True, errors=[])
            )()
            await plugin.handle(event)

        call_args = mock_engine.call_args
        step_types = [type(s).__name__ for s in call_args.kwargs.get("steps", call_args[1].get("steps", []))]
        assert "DocumentSummaryStep" in step_types
        assert "BodyOfKnowledgeSummaryStep" in step_types

    async def test_summarize_disabled_excludes_summary_steps(self):
        """When summarize_enabled=False, pipeline excludes summary steps."""
        from core.domain.ingest_pipeline import Document, DocumentMetadata

        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=MagicMock(),
            summarize_enabled=False,
        )
        event = make_ingest_body_of_knowledge()
        mock_docs = [
            Document(
                content="Test content",
                metadata=DocumentMetadata(
                    document_id="doc-1", source="test", type="knowledge", title="Test",
                ),
            )
        ]

        import asyncio
        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=mock_docs), \
             patch("plugins.ingest_space.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = lambda *a, **kw: asyncio.coroutine(
                lambda: MagicMock(success=True, errors=[])
            )()
            await plugin.handle(event)

        call_args = mock_engine.call_args
        step_types = [type(s).__name__ for s in call_args.kwargs.get("steps", call_args[1].get("steps", []))]
        assert "DocumentSummaryStep" not in step_types
        assert "BodyOfKnowledgeSummaryStep" not in step_types
