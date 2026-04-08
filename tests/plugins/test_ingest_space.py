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

    async def test_pipeline_includes_summary_steps_by_default(self):
        """Both summary steps are included when summarize_enabled=True (default)."""
        mock_graphql = MagicMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=mock_graphql,
        )
        event = make_ingest_body_of_knowledge()

        mock_config = MagicMock()
        mock_config.summarize_enabled = True
        mock_config.summarize_concurrency = 8

        from core.domain.ingest_pipeline import Document, DocumentMetadata
        mock_docs = [Document(
            content="Test document content for summary inclusion.",
            metadata=DocumentMetadata(
                document_id="doc-1", source="test", type="knowledge", title="Test",
            ),
        )]

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=mock_docs), \
             patch("core.config.IngestSpaceConfig", return_value=mock_config), \
             patch("plugins.ingest_space.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = MagicMock(return_value=MagicMock(success=True, errors=[]))
            await plugin.handle(event)

        call_kwargs = mock_engine.call_args
        if hasattr(call_kwargs, "kwargs") and "steps" in call_kwargs.kwargs:
            steps = call_kwargs.kwargs["steps"]
        else:
            steps = call_kwargs[0][0] if call_kwargs[0] else []
        step_types = [type(s).__name__ for s in steps]
        assert "DocumentSummaryStep" in step_types
        assert "BodyOfKnowledgeSummaryStep" in step_types

    async def test_pipeline_skips_summary_when_disabled(self):
        """Summary steps are excluded when summarize_enabled=False."""
        mock_graphql = MagicMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=mock_graphql,
        )
        event = make_ingest_body_of_knowledge()

        mock_config = MagicMock()
        mock_config.summarize_enabled = False
        mock_config.summarize_concurrency = 8

        from core.domain.ingest_pipeline import Document, DocumentMetadata
        mock_docs = [Document(
            content="Test document content for disabled summary.",
            metadata=DocumentMetadata(
                document_id="doc-1", source="test", type="knowledge", title="Test",
            ),
        )]

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=mock_docs), \
             patch("core.config.IngestSpaceConfig", return_value=mock_config), \
             patch("plugins.ingest_space.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = MagicMock(return_value=MagicMock(success=True, errors=[]))
            await plugin.handle(event)

        call_kwargs = mock_engine.call_args
        if hasattr(call_kwargs, "kwargs") and "steps" in call_kwargs.kwargs:
            steps = call_kwargs.kwargs["steps"]
        else:
            steps = call_kwargs[0][0] if call_kwargs[0] else []
        step_types = [type(s).__name__ for s in steps]
        assert "DocumentSummaryStep" not in step_types
        assert "BodyOfKnowledgeSummaryStep" not in step_types

    async def test_concurrency_zero_maps_to_one(self):
        """summarize_concurrency=0 should result in concurrency=1 (sequential)."""
        mock_graphql = MagicMock()
        plugin = IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=mock_graphql,
        )
        event = make_ingest_body_of_knowledge()

        mock_config = MagicMock()
        mock_config.summarize_enabled = True
        mock_config.summarize_concurrency = 0

        from core.domain.ingest_pipeline import Document, DocumentMetadata
        mock_docs = [Document(
            content="Test document content for concurrency zero.",
            metadata=DocumentMetadata(
                document_id="doc-1", source="test", type="knowledge", title="Test",
            ),
        )]

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=mock_docs), \
             patch("core.config.IngestSpaceConfig", return_value=mock_config), \
             patch("plugins.ingest_space.plugin.DocumentSummaryStep") as mock_step, \
             patch("plugins.ingest_space.plugin.IngestEngine") as mock_engine:
            mock_engine.return_value.run = MagicMock(return_value=MagicMock(success=True, errors=[]))
            await plugin.handle(event)

        mock_step.assert_called_once()
        call_kwargs = mock_step.call_args
        assert call_kwargs.kwargs.get("concurrency") == 1 or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == 1
        )
