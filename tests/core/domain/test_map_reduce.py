"""Unit tests for _map_reduce_summarize and LLM port wiring on summary steps."""

from __future__ import annotations

import asyncio

import pytest

from core.domain.ingest_pipeline import Chunk, Document, DocumentMetadata
from core.domain.pipeline.engine import PipelineContext
from core.domain.pipeline.steps import (
    BodyOfKnowledgeSummaryStep,
    DocumentSummaryStep,
    _map_reduce_summarize,
)
from tests.conftest import MockEmbeddingsPort, MockLLMPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(
    content: str = "Test content. " * 100,
    doc_id: str = "doc-1",
    source: str = "test-source",
) -> Document:
    return Document(
        content=content,
        metadata=DocumentMetadata(
            document_id=doc_id,
            source=source,
            type="knowledge",
            title="Test Doc",
        ),
    )


def _make_context(
    docs: list[Document] | None = None,
    collection: str = "test-collection",
) -> PipelineContext:
    return PipelineContext(
        collection_name=collection,
        documents=docs or [_make_doc()],
    )


# Default kwargs shared by most _map_reduce_summarize tests.
_DEFAULT_KWARGS = dict(
    max_length=2000,
    map_system="system-map",
    map_template="Summarize:\n{text}\nBudget: {budget}",
    reduce_system="system-reduce",
    reduce_template="Merge:\n{summaries}\nBudget: {budget}",
)


# ---------------------------------------------------------------------------
# TestMapReduceSummarize
# ---------------------------------------------------------------------------


class TestMapReduceSummarize:
    async def test_empty_chunks_returns_empty(self):
        mock_map = MockLLMPort(response="m")
        mock_reduce = MockLLMPort(response="r")
        result = await _map_reduce_summarize(
            [],
            map_invoke=mock_map.invoke,
            reduce_invoke=mock_reduce.invoke,
            **_DEFAULT_KWARGS,
        )
        assert result == ""
        assert mock_map.calls == []
        assert mock_reduce.calls == []

    async def test_single_chunk_uses_map_only(self):
        mock_map = MockLLMPort(response="map-result")
        mock_reduce = MockLLMPort(response="reduce-result")
        result = await _map_reduce_summarize(
            ["chunk-A"],
            map_invoke=mock_map.invoke,
            reduce_invoke=mock_reduce.invoke,
            **_DEFAULT_KWARGS,
        )
        assert result == "map-result"
        assert len(mock_map.calls) == 1
        assert mock_reduce.calls == []

    async def test_single_chunk_map_failure_returns_empty(self):
        call_count = 0

        async def failing_map(messages):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("LLM error")

        mock_reduce = MockLLMPort(response="r")
        result = await _map_reduce_summarize(
            ["chunk-A"],
            map_invoke=failing_map,
            reduce_invoke=mock_reduce.invoke,
            **_DEFAULT_KWARGS,
        )
        assert result == ""
        assert call_count == 1
        assert mock_reduce.calls == []

    async def test_multiple_chunks_calls_map_then_reduce(self):
        mock_map = MockLLMPort(response="mini")
        mock_reduce = MockLLMPort(response="final")
        result = await _map_reduce_summarize(
            ["c1", "c2", "c3"],
            map_invoke=mock_map.invoke,
            reduce_invoke=mock_reduce.invoke,
            reduce_fanin=10,
            **_DEFAULT_KWARGS,
        )
        assert result == "final"
        assert len(mock_map.calls) == 3
        assert len(mock_reduce.calls) == 1

    async def test_concurrency_bounded_by_semaphore(self):
        """At most `concurrency` map calls should run simultaneously."""
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracking_map(messages):
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            # Yield control so other tasks can schedule
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return "mini"

        mock_reduce = MockLLMPort(response="final")
        await _map_reduce_summarize(
            [f"chunk-{i}" for i in range(10)],
            map_invoke=tracking_map,
            reduce_invoke=mock_reduce.invoke,
            concurrency=2,
            reduce_fanin=20,
            **_DEFAULT_KWARGS,
        )
        assert max_concurrent <= 2

    async def test_tree_reduce_multiple_levels(self):
        """7 chunks with reduce_fanin=3 needs two reduce levels.

        Level 1: [0,1,2] -> r1, [3,4,5] -> r2, [6] passthrough -> 3 results
        Level 2: [r1,r2,6] -> final -> 1 result
        Total reduce calls: 3 (2 at level 1 + 1 at level 2)
        """
        mock_map = MockLLMPort(response="mini")
        mock_reduce = MockLLMPort(response="merged")
        await _map_reduce_summarize(
            [f"chunk-{i}" for i in range(7)],
            map_invoke=mock_map.invoke,
            reduce_invoke=mock_reduce.invoke,
            reduce_fanin=3,
            **_DEFAULT_KWARGS,
        )
        assert len(mock_map.calls) == 7
        # Level 1: batch [0..2] -> reduce, batch [3..5] -> reduce, batch [6] passthrough
        # Level 2: 3 items -> 1 batch -> reduce
        assert len(mock_reduce.calls) == 3

    async def test_map_failure_skipped_gracefully(self):
        """If one map call fails, the remaining summaries still get reduced."""
        call_idx = 0

        async def selective_map(messages):
            nonlocal call_idx
            idx = call_idx
            call_idx += 1
            if idx == 1:
                raise RuntimeError("LLM error on chunk 1")
            return f"mini-{idx}"

        mock_reduce = MockLLMPort(response="final")
        result = await _map_reduce_summarize(
            ["c0", "c1", "c2"],
            map_invoke=selective_map,
            reduce_invoke=mock_reduce.invoke,
            reduce_fanin=10,
            **_DEFAULT_KWARGS,
        )
        assert result == "final"
        assert len(mock_reduce.calls) == 1
        # The reduce call should receive 2 mini-summaries (chunk 0 and chunk 2)
        reduce_human_msg = mock_reduce.calls[0][1]["content"]
        assert "mini-0" in reduce_human_msg
        assert "mini-2" in reduce_human_msg

    async def test_all_maps_fail_returns_empty(self):
        async def always_fail(messages):
            raise RuntimeError("LLM error")

        mock_reduce = MockLLMPort(response="r")
        result = await _map_reduce_summarize(
            ["c0", "c1", "c2"],
            map_invoke=always_fail,
            reduce_invoke=mock_reduce.invoke,
            **_DEFAULT_KWARGS,
        )
        assert result == ""
        assert mock_reduce.calls == []

    async def test_reduce_failure_falls_back_to_concatenation(self):
        mock_map = MockLLMPort(response="mini")

        async def failing_reduce(messages):
            raise RuntimeError("reduce error")

        result = await _map_reduce_summarize(
            ["c0", "c1", "c2", "c3"],
            map_invoke=mock_map.invoke,
            reduce_invoke=failing_reduce,
            reduce_fanin=4,
            **_DEFAULT_KWARGS,
        )
        # All 4 fit in one batch; reduce fails -> concatenation fallback
        assert result == "\n\n---\n\n".join(["mini"] * 4)

    async def test_per_chunk_budget_calculation(self):
        """4 chunks, max_length=2000 -> per_chunk_budget = max(500, 2000//4) = 500."""
        mock_map = MockLLMPort(response="mini")
        mock_reduce = MockLLMPort(response="final")
        await _map_reduce_summarize(
            ["c0", "c1", "c2", "c3"],
            map_invoke=mock_map.invoke,
            reduce_invoke=mock_reduce.invoke,
            reduce_fanin=10,
            **_DEFAULT_KWARGS,
        )
        # budget = max(500, 2000 // max(2, 4)) = max(500, 500) = 500
        for call in mock_map.calls:
            human_content = call[1]["content"]
            assert "Budget: 500" in human_content

    async def test_per_chunk_budget_floor_at_500(self):
        """100 chunks, max_length=2000 -> budget = max(500, 2000//100) = 500, not 20."""
        mock_map = MockLLMPort(response="mini")
        mock_reduce = MockLLMPort(response="final")
        await _map_reduce_summarize(
            [f"chunk-{i}" for i in range(100)],
            map_invoke=mock_map.invoke,
            reduce_invoke=mock_reduce.invoke,
            reduce_fanin=50,
            **_DEFAULT_KWARGS,
        )
        # Without floor: 2000 // 100 = 20.  With floor: max(500, 20) = 500.
        for call in mock_map.calls:
            human_content = call[1]["content"]
            assert "Budget: 500" in human_content


# ---------------------------------------------------------------------------
# TestDocumentSummaryStepReduceLLM
# ---------------------------------------------------------------------------


class TestDocumentSummaryStepReduceLLM:
    async def test_reduce_llm_port_used_for_reduce(self):
        """When reduce_llm_port is provided, it handles reduce calls."""
        map_llm = MockLLMPort(response="map-mini")
        reduce_llm = MockLLMPort(response="reduce-merged")

        step = DocumentSummaryStep(
            llm_port=map_llm,
            reduce_llm_port=reduce_llm,
            chunk_threshold=1,
            summary_length=2000,
            concurrency=4,
        )

        # Build a context with a document that has enough chunks to
        # trigger both map (>1 chunk) and reduce.
        doc = _make_doc(doc_id="doc-1")
        ctx = _make_context([doc])
        # Manually create 4 chunks for the document
        for i in range(4):
            ctx.chunks.append(
                Chunk(
                    content=f"chunk content {i}",
                    metadata=DocumentMetadata(
                        document_id="doc-1",
                        source="test-source",
                        type="knowledge",
                        title="Test Doc",
                        embedding_type="chunk",
                    ),
                    chunk_index=i,
                )
            )

        await step.execute(ctx)

        assert len(map_llm.calls) > 0, "map LLM should be called for map phase"
        assert len(reduce_llm.calls) > 0, "reduce LLM should be called for reduce phase"

    async def test_reduce_llm_defaults_to_llm_port(self):
        """Without reduce_llm_port, the main llm_port handles both phases."""
        llm = MockLLMPort(response="summary-text")

        step = DocumentSummaryStep(
            llm_port=llm,
            chunk_threshold=1,
            summary_length=2000,
            concurrency=4,
        )

        doc = _make_doc(doc_id="doc-1")
        ctx = _make_context([doc])
        for i in range(4):
            ctx.chunks.append(
                Chunk(
                    content=f"chunk content {i}",
                    metadata=DocumentMetadata(
                        document_id="doc-1",
                        source="test-source",
                        type="knowledge",
                        title="Test Doc",
                        embedding_type="chunk",
                    ),
                    chunk_index=i,
                )
            )

        await step.execute(ctx)

        # All calls (map + reduce) go through the single LLM port
        assert len(llm.calls) > 0
        assert "doc-1" in ctx.document_summaries


# ---------------------------------------------------------------------------
# TestBoKSummaryStepMapLLM
# ---------------------------------------------------------------------------


class TestBoKSummaryStepMapLLM:
    async def test_map_llm_port_used_for_map(self):
        """When map_llm_port is provided, it handles map calls."""
        main_llm = MockLLMPort(response="reduce-bok")
        map_llm = MockLLMPort(response="map-section")

        # Use a very small max_section_chars so the three summaries are
        # NOT grouped into a single section -- each stays separate,
        # guaranteeing that _map_reduce_summarize receives >1 chunk
        # and both map (map_llm) and reduce (main_llm) are exercised.
        step = BodyOfKnowledgeSummaryStep(
            llm_port=main_llm,
            map_llm_port=map_llm,
            summary_length=2000,
            max_section_chars=1000,  # floor enforced at 1000
        )

        # Build long-enough summaries that exceed max_section_chars
        # individually so grouping cannot merge them.
        long_summary = "x" * 1100
        doc1 = _make_doc(doc_id="doc-1")
        doc2 = _make_doc(doc_id="doc-2")
        doc3 = _make_doc(doc_id="doc-3")
        ctx = _make_context([doc1, doc2, doc3])
        ctx.document_summaries = {
            "doc-1": long_summary,
            "doc-2": long_summary,
            "doc-3": long_summary,
        }
        # Need at least one chunk per doc so seen_doc_ids gets populated
        for d_id in ["doc-1", "doc-2", "doc-3"]:
            ctx.chunks.append(
                Chunk(
                    content="content",
                    metadata=DocumentMetadata(
                        document_id=d_id,
                        source="test-source",
                        type="knowledge",
                        title="Test Doc",
                        embedding_type="chunk",
                    ),
                    chunk_index=0,
                )
            )

        await step.execute(ctx)

        assert len(map_llm.calls) > 0, "map_llm should be called for map phase"
        assert len(main_llm.calls) > 0, "main llm should be called for reduce phase"

    async def test_map_llm_defaults_to_llm_port(self):
        """Without map_llm_port, the main llm_port handles both phases."""
        llm = MockLLMPort(response="bok-overview")

        step = BodyOfKnowledgeSummaryStep(
            llm_port=llm,
            summary_length=2000,
        )

        doc1 = _make_doc(doc_id="doc-1")
        doc2 = _make_doc(doc_id="doc-2")
        ctx = _make_context([doc1, doc2])
        ctx.document_summaries = {
            "doc-1": "Summary of doc 1",
            "doc-2": "Summary of doc 2",
        }
        for d_id in ["doc-1", "doc-2"]:
            ctx.chunks.append(
                Chunk(
                    content="content",
                    metadata=DocumentMetadata(
                        document_id=d_id,
                        source="test-source",
                        type="knowledge",
                        title="Test Doc",
                        embedding_type="chunk",
                    ),
                    chunk_index=0,
                )
            )

        await step.execute(ctx)

        assert len(llm.calls) > 0
        # BoK summary chunk should be appended
        bok_chunks = [
            c for c in ctx.chunks
            if c.metadata.embedding_type == "summary"
            and c.metadata.document_id == "body-of-knowledge-summary"
        ]
        assert len(bok_chunks) == 1
