"""Tests for SUMMARY_CHUNK_THRESHOLD behavior in DocumentSummaryStep."""

from __future__ import annotations

import pytest

from core.config import BaseConfig
from core.domain.ingest_pipeline import Chunk, DocumentMetadata
from core.domain.pipeline.engine import PipelineContext
from core.domain.pipeline.steps import DocumentSummaryStep


def _make_chunks(doc_id: str, count: int) -> list[Chunk]:
    """Create N chunks for a document."""
    return [
        Chunk(
            content=f"Content of chunk {i} for {doc_id}",
            metadata=DocumentMetadata(
                document_id=doc_id,
                source="test",
                type="knowledge",
                title=f"Doc {doc_id}",
                embedding_type="chunk",
            ),
            chunk_index=i,
        )
        for i in range(count)
    ]


class TestChunkThresholdBehavior:
    """Test that chunk threshold controls which docs get summarized."""

    @pytest.mark.asyncio
    async def test_docs_below_threshold_not_summarized(self, mock_llm) -> None:
        step = DocumentSummaryStep(llm_port=mock_llm, chunk_threshold=5)
        context = PipelineContext(collection_name="test", documents=[])
        context.chunks.extend(_make_chunks("doc-1", 4))  # 4 < 5, skip

        await step.execute(context)

        assert "doc-1" not in context.document_summaries
        assert len(mock_llm.calls) == 0

    @pytest.mark.asyncio
    async def test_docs_at_threshold_are_summarized(self, mock_llm) -> None:
        step = DocumentSummaryStep(llm_port=mock_llm, chunk_threshold=5)
        context = PipelineContext(collection_name="test", documents=[])
        context.chunks.extend(_make_chunks("doc-1", 5))  # 5 >= 5, summarize

        await step.execute(context)

        assert "doc-1" in context.document_summaries

    @pytest.mark.asyncio
    async def test_docs_above_threshold_are_summarized(self, mock_llm) -> None:
        step = DocumentSummaryStep(llm_port=mock_llm, chunk_threshold=5)
        context = PipelineContext(collection_name="test", documents=[])
        context.chunks.extend(_make_chunks("doc-1", 6))  # 6 >= 5, summarize

        await step.execute(context)

        assert "doc-1" in context.document_summaries

    @pytest.mark.asyncio
    async def test_default_4_preserves_current_behavior(self, mock_llm) -> None:
        """Default threshold=4 with >= preserves old > 3 behavior."""
        step = DocumentSummaryStep(llm_port=mock_llm)  # default chunk_threshold=4

        # 3 chunks: should NOT be summarized (3 < 4)
        context_3 = PipelineContext(collection_name="test", documents=[])
        context_3.chunks.extend(_make_chunks("doc-3chunks", 3))
        await step.execute(context_3)
        assert "doc-3chunks" not in context_3.document_summaries

        # 4 chunks: should be summarized (4 >= 4)
        context_4 = PipelineContext(collection_name="test", documents=[])
        context_4.chunks.extend(_make_chunks("doc-4chunks", 4))
        await step.execute(context_4)
        assert "doc-4chunks" in context_4.document_summaries


class TestChunkThresholdConfigValidation:
    """Test config validation for summary_chunk_threshold."""

    def test_default_is_4(self) -> None:
        config = BaseConfig(llm_api_key="key")
        assert config.summary_chunk_threshold == 4

    def test_rejects_zero(self) -> None:
        with pytest.raises(ValueError, match="SUMMARY_CHUNK_THRESHOLD"):
            BaseConfig(llm_api_key="key", summary_chunk_threshold=0)

    def test_rejects_negative(self) -> None:
        with pytest.raises(ValueError, match="SUMMARY_CHUNK_THRESHOLD"):
            BaseConfig(llm_api_key="key", summary_chunk_threshold=-1)

    def test_accepts_positive(self) -> None:
        config = BaseConfig(llm_api_key="key", summary_chunk_threshold=10)
        assert config.summary_chunk_threshold == 10
