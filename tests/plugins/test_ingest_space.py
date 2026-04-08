"""Unit tests for IngestSpacePlugin."""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from core.domain.ingest_pipeline import Document, DocumentMetadata
from core.domain.pipeline import IngestEngine
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


class TestIngestSpaceSummarizationToggle:
    """Tests for the summarize_enabled config flag in ingest-space."""

    @pytest.fixture
    def plugin(self):
        mock_graphql = AsyncMock()
        return IngestSpacePlugin(
            llm=MockLLMPort(),
            embeddings=MockEmbeddingsPort(),
            knowledge_store=MockKnowledgeStorePort(),
            graphql_client=mock_graphql,
        )

    def _make_documents(self):
        return [
            Document(
                content="Test document content for pipeline test.",
                metadata=DocumentMetadata(
                    document_id="doc-1",
                    source="space-1",
                    type="knowledge",
                    title="Test Doc",
                ),
            )
        ]

    async def test_pipeline_includes_summary_steps_when_enabled(self, plugin):
        """When summarize_enabled=True, pipeline includes both summary steps."""
        event = make_ingest_body_of_knowledge()

        mock_config = MagicMock()
        mock_config.summarize_enabled = True
        mock_config.summarize_concurrency = 8

        captured_steps = []

        def capture_engine_init(self_engine, steps, **kwargs):
            captured_steps.extend(steps)
            self_engine._steps = steps

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=self._make_documents()), \
             patch("core.config.BaseConfig", return_value=mock_config), \
             patch.object(IngestEngine, "__init__", capture_engine_init), \
             patch.object(IngestEngine, "run", return_value=MagicMock(success=True, errors=[])):
            await plugin.handle(event)

        step_names = [type(s).__name__ for s in captured_steps]
        assert "DocumentSummaryStep" in step_names
        assert "BodyOfKnowledgeSummaryStep" in step_names

    async def test_pipeline_excludes_summary_steps_when_disabled(self, plugin):
        """When summarize_enabled=False, pipeline omits both summary steps."""
        event = make_ingest_body_of_knowledge()

        mock_config = MagicMock()
        mock_config.summarize_enabled = False

        captured_steps = []

        def capture_engine_init(self_engine, steps, **kwargs):
            captured_steps.extend(steps)
            self_engine._steps = steps

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=self._make_documents()), \
             patch("core.config.BaseConfig", return_value=mock_config), \
             patch.object(IngestEngine, "__init__", capture_engine_init), \
             patch.object(IngestEngine, "run", return_value=MagicMock(success=True, errors=[])):
            await plugin.handle(event)

        step_names = [type(s).__name__ for s in captured_steps]
        assert "DocumentSummaryStep" not in step_names
        assert "BodyOfKnowledgeSummaryStep" not in step_names

    async def test_pipeline_coerces_zero_concurrency(self, plugin):
        """When summarize_concurrency=0 and summarize_enabled=True, concurrency defaults to 8."""
        event = make_ingest_body_of_knowledge()

        mock_config = MagicMock()
        mock_config.summarize_enabled = True
        mock_config.summarize_concurrency = 0

        captured_steps = []

        def capture_engine_init(self_engine, steps, **kwargs):
            captured_steps.extend(steps)
            self_engine._steps = steps

        with patch("plugins.ingest_space.space_reader.read_space_tree", return_value=self._make_documents()), \
             patch("core.config.BaseConfig", return_value=mock_config), \
             patch.object(IngestEngine, "__init__", capture_engine_init), \
             patch.object(IngestEngine, "run", return_value=MagicMock(success=True, errors=[])):
            await plugin.handle(event)

        doc_summary_steps = [s for s in captured_steps if type(s).__name__ == "DocumentSummaryStep"]
        assert len(doc_summary_steps) == 1
        assert doc_summary_steps[0]._concurrency == 8
