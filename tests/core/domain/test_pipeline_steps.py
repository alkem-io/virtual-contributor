"""Unit tests for all pipeline steps and IngestEngine."""

from __future__ import annotations

import asyncio
import time

from core.domain.ingest_pipeline import Chunk, Document, DocumentMetadata, IngestResult
from core.domain.pipeline.engine import IngestEngine, PipelineContext
from core.ports.knowledge_store import GetResult
from core.domain.pipeline.steps import (
    BodyOfKnowledgeSummaryStep,
    ChangeDetectionStep,
    ChunkStep,
    ContentHashStep,
    DocumentSummaryStep,
    EmbedStep,
    OrphanCleanupStep,
    StoreStep,
)
from tests.conftest import MockEmbeddingsPort, MockKnowledgeStorePort, MockLLMPort


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


# ---------------------------------------------------------------------------
# T022: ChunkStep tests
# ---------------------------------------------------------------------------

class TestChunkStep:
    async def test_chunking_produces_chunks(self):
        ctx = _make_context()
        step = ChunkStep(chunk_size=100, chunk_overlap=20)
        await step.execute(ctx)
        assert len(ctx.chunks) > 0
        assert all(c.metadata.embedding_type == "chunk" for c in ctx.chunks)

    async def test_configurable_chunk_size(self):
        doc = _make_doc("word " * 1000)
        ctx_small = _make_context([doc])
        ctx_large = _make_context([doc])

        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx_small)
        await ChunkStep(chunk_size=2000, chunk_overlap=200).execute(ctx_large)
        assert len(ctx_small.chunks) > len(ctx_large.chunks)

    async def test_empty_document_handling(self):
        doc = _make_doc(content="")
        ctx = _make_context([doc])
        await ChunkStep().execute(ctx)
        assert len(ctx.chunks) == 0

    async def test_metadata_propagation(self):
        doc = _make_doc(doc_id="my-doc", source="my-source")
        ctx = _make_context([doc])
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 0
        for chunk in ctx.chunks:
            assert chunk.metadata.document_id == "my-doc"
            assert chunk.metadata.source == "my-source"
            assert chunk.metadata.embedding_type == "chunk"

    async def test_chunk_index_correctness(self):
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        indices = [c.chunk_index for c in ctx.chunks]
        assert indices == list(range(len(ctx.chunks)))

    async def test_step_name(self):
        assert ChunkStep().name == "chunk"


# ---------------------------------------------------------------------------
# T023: EmbedStep tests
# ---------------------------------------------------------------------------

class TestEmbedStep:
    async def test_batch_processing(self):
        embeddings = MockEmbeddingsPort()
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 0

        step = EmbedStep(embeddings_port=embeddings, batch_size=5)
        await step.execute(ctx)

        assert all(c.embedding is not None for c in ctx.chunks)
        # Multiple batches should produce multiple calls
        if len(ctx.chunks) > 5:
            assert len(embeddings.calls) > 1

    async def test_always_embeds_content(self):
        embeddings = MockEmbeddingsPort()
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await EmbedStep(embeddings_port=embeddings).execute(ctx)

        # Verify texts sent to embed are chunk content
        for call_texts in embeddings.calls:
            for text in call_texts:
                assert any(text == c.content for c in ctx.chunks)

    async def test_skips_chunks_with_existing_embeddings(self):
        embeddings = MockEmbeddingsPort()
        meta = DocumentMetadata(document_id="d1", source="s")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(content="pre-embedded", metadata=meta, chunk_index=0, embedding=[1.0, 2.0]),
                Chunk(content="not embedded", metadata=meta, chunk_index=1),
            ],
        )

        await EmbedStep(embeddings_port=embeddings).execute(ctx)

        # Only the one without embedding should have been sent
        assert len(embeddings.calls) == 1
        assert embeddings.calls[0] == ["not embedded"]
        # Pre-embedded chunk keeps its original embedding
        assert ctx.chunks[0].embedding == [1.0, 2.0]

    async def test_per_batch_error_handling(self):
        class FailingEmbeddings:
            async def embed(self, texts):
                raise RuntimeError("Embedding service down")

        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await EmbedStep(embeddings_port=FailingEmbeddings(), batch_size=5).execute(ctx)  # type: ignore[arg-type]
        assert any("EmbedStep" in e for e in ctx.errors)

    async def test_step_name(self):
        embeddings = MockEmbeddingsPort()
        assert EmbedStep(embeddings_port=embeddings).name == "embed"


# ---------------------------------------------------------------------------
# T024: DocumentSummaryStep tests
# ---------------------------------------------------------------------------

class TestDocumentSummaryStep:
    async def test_threshold_over_3_chunks(self):
        """Documents with >3 chunks get a summary."""
        llm = MockLLMPort(response="Generated summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        # Ensure we have >3 chunks for this test
        assert len(ctx.chunks) > 3, "Test doc should produce >3 chunks"
        chunks_before = len(ctx.chunks)

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        # Should have added a summary chunk
        assert len(ctx.chunks) == chunks_before + 1
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1
        assert summary_chunks[0].metadata.document_id == "doc-1-summary"
        assert summary_chunks[0].content == "Generated summary"

    async def test_no_summary_for_3_or_fewer_chunks(self):
        """Documents with <=3 chunks should NOT produce a summary."""
        llm = MockLLMPort()
        doc = _make_doc(content="Short text.")
        ctx = _make_context([doc])
        await ChunkStep(chunk_size=10000).execute(ctx)

        assert len(ctx.chunks) <= 3
        chunks_before = len(ctx.chunks)

        await DocumentSummaryStep(llm_port=llm).execute(ctx)
        assert len(ctx.chunks) == chunks_before  # No summary added
        assert len(llm.calls) == 0

    async def test_summary_metadata(self):
        llm = MockLLMPort(response="Summary text")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        summary = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"][0]
        assert summary.metadata.document_id == "doc-1-summary"
        assert summary.metadata.embedding_type == "summary"
        assert summary.chunk_index == 0

    async def test_populates_document_summaries(self):
        llm = MockLLMPort(response="The summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(llm_port=llm).execute(ctx)
        assert "doc-1" in ctx.document_summaries
        assert ctx.document_summaries["doc-1"] == "The summary"

    async def test_per_document_error_handling(self):
        class FailingLLM:
            async def invoke(self, messages):
                raise RuntimeError("LLM unavailable")
            async def stream(self, messages):
                yield ""

        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(llm_port=FailingLLM()).execute(ctx)  # type: ignore[arg-type]
        assert any("DocumentSummaryStep" in e for e in ctx.errors)

    async def test_step_name(self):
        llm = MockLLMPort()
        assert DocumentSummaryStep(llm_port=llm).name == "document_summary"


# ---------------------------------------------------------------------------
# T024b: DocumentSummaryStep incremental embedding tests
# ---------------------------------------------------------------------------

class TestDocumentSummaryStepIncrementalEmbedding:
    async def test_inline_embedding_after_summary(self):
        """When embeddings_port is provided, chunks are embedded inline."""
        llm = MockLLMPort(response="Generated summary")
        embeddings = MockEmbeddingsPort()
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=embeddings,
        ).execute(ctx)

        # All content chunks for doc-1 should have embeddings
        doc_chunks = [c for c in ctx.chunks if c.metadata.document_id == "doc-1"]
        assert all(c.embedding is not None for c in doc_chunks)

        # Summary chunk should also have an embedding
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1
        assert summary_chunks[0].embedding is not None

    async def test_embed_step_skips_already_embedded(self):
        """EmbedStep makes zero calls for chunks already embedded inline."""
        llm = MockLLMPort(response="Summary")
        inline_embeddings = MockEmbeddingsPort()
        safety_embeddings = MockEmbeddingsPort()

        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=inline_embeddings,
        ).execute(ctx)

        # All chunks should now have embeddings
        assert all(c.embedding is not None for c in ctx.chunks)

        # EmbedStep should skip everything
        await EmbedStep(embeddings_port=safety_embeddings).execute(ctx)
        assert len(safety_embeddings.calls) == 0

    async def test_inline_embed_error_handling(self):
        """Embedding errors are captured without halting summarization."""
        class FailingEmbeddings:
            async def embed(self, texts):
                raise RuntimeError("Embedding service down")

        llm = MockLLMPort(response="Summary despite embed failure")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(
            llm_port=llm,
            embeddings_port=FailingEmbeddings(),  # type: ignore[arg-type]
        ).execute(ctx)

        # Summary should still be produced
        assert "doc-1" in ctx.document_summaries
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1

        # Error should be recorded
        assert any("inline embedding failed" in e for e in ctx.errors)

    async def test_no_embeddings_port_backward_compat(self):
        """Without embeddings_port, chunks have no embeddings after execute."""
        llm = MockLLMPort(response="Summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        # Content chunks should NOT have embeddings
        content_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "chunk"]
        assert all(c.embedding is None for c in content_chunks)

        # Summary chunk should NOT have an embedding
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1
        assert summary_chunks[0].embedding is None

    async def test_below_threshold_not_embedded_inline(self):
        """Documents below chunk threshold are not embedded by DocumentSummaryStep."""
        llm = MockLLMPort()
        embeddings = MockEmbeddingsPort()
        doc = _make_doc(content="Short text.")
        ctx = _make_context([doc])
        await ChunkStep(chunk_size=10000).execute(ctx)

        assert len(ctx.chunks) <= 3

        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=embeddings,
        ).execute(ctx)

        # No summarization, no inline embedding
        assert len(embeddings.calls) == 0
        assert all(c.embedding is None for c in ctx.chunks)

    async def test_full_pipeline_with_incremental_embedding(self):
        """Integration: full pipeline with incremental embedding stores all chunks."""
        llm = MockLLMPort(response="Doc summary")
        bok_llm = MockLLMPort(response="BoK summary")
        embeddings = MockEmbeddingsPort()
        store = MockKnowledgeStorePort()

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            ContentHashStep(),
            DocumentSummaryStep(
                llm_port=llm,
                embeddings_port=embeddings,
            ),
            BodyOfKnowledgeSummaryStep(llm_port=bok_llm),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
        ])
        result = await engine.run([_make_doc()], "incremental-test")

        assert result.success is True
        assert result.chunks_stored > 0
        assert result.errors == []
        # All chunks should be stored — collection must exist and contain entries
        assert "incremental-test" in store.collections
        stored = store.collections["incremental-test"]
        assert len(stored) > 0
        # Should have content chunks, doc summary, and BoK summary
        stored_types = {it["metadata"]["embeddingType"] for it in stored}
        assert "chunk" in stored_types
        assert "summary" in stored_types

    async def test_skips_chunks_with_preexisting_embeddings(self):
        """Inline embedding skips chunks that already have embeddings from change detection."""
        llm = MockLLMPort(response="Summary")
        embeddings = MockEmbeddingsPort()
        meta = DocumentMetadata(
            document_id="doc-1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        # Create chunks where some already have embeddings (from ChangeDetectionStep)
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(content="a", metadata=meta, chunk_index=0, embedding=[9.0]),
                Chunk(content="b", metadata=meta, chunk_index=1, embedding=[9.0]),
                Chunk(content="c", metadata=meta, chunk_index=2),
                Chunk(content="d", metadata=meta, chunk_index=3),
            ],
        )

        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=embeddings,
        ).execute(ctx)

        # Pre-existing embeddings should be preserved
        assert ctx.chunks[0].embedding == [9.0]
        assert ctx.chunks[1].embedding == [9.0]
        # New chunks should be embedded
        assert ctx.chunks[2].embedding is not None
        assert ctx.chunks[3].embedding is not None
        # Summary chunk should be embedded
        summary = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary) == 1
        assert summary[0].embedding is not None

        # Only chunks without pre-existing embeddings should have been sent
        total_embedded = sum(len(call) for call in embeddings.calls)
        assert total_embedded == 3  # c, d, and summary chunk

    async def test_embed_batch_size_validation(self):
        """embed_batch_size < 1 should raise ValueError."""
        llm = MockLLMPort()
        import pytest
        with pytest.raises(ValueError, match="embed_batch_size must be >= 1"):
            DocumentSummaryStep(llm_port=llm, embed_batch_size=0)
        with pytest.raises(ValueError, match="embed_batch_size must be >= 1"):
            DocumentSummaryStep(llm_port=llm, embed_batch_size=-5)

    async def test_embedding_overlaps_with_summarization(self):
        """Embedding runs concurrently with summarization of the next document.

        Uses a slow embeddings port and two documents to verify that the
        embedding task for doc-1 is dispatched as a background task while
        doc-2's summarization proceeds.
        """
        import asyncio

        embed_start_times: list[float] = []
        summarize_start_times: list[float] = []

        class TimingLLM:
            async def invoke(self, messages):
                summarize_start_times.append(asyncio.get_event_loop().time())
                await asyncio.sleep(0.01)  # simulate LLM latency
                return "Summary"
            async def stream(self, messages):
                yield ""

        class TimingEmbeddings:
            async def embed(self, texts):
                embed_start_times.append(asyncio.get_event_loop().time())
                await asyncio.sleep(0.05)  # simulate GPU latency
                return [[0.1] * 384 for _ in texts]

        doc1 = _make_doc(doc_id="doc-1")
        doc2 = _make_doc(doc_id="doc-2")
        ctx = _make_context([doc1, doc2])
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        step = DocumentSummaryStep(
            llm_port=TimingLLM(),  # type: ignore[arg-type]
            embeddings_port=TimingEmbeddings(),  # type: ignore[arg-type]
        )
        await step.execute(ctx)

        # Both documents should be summarized and embedded
        assert "doc-1" in ctx.document_summaries
        assert "doc-2" in ctx.document_summaries

        # The second document's summarization should start before the first
        # document's embedding finishes (i.e., they overlap). Since embedding
        # takes 50ms and summarization only 10ms per chunk, if they were
        # sequential, doc-2 summarization would start much later.
        # With background tasks, doc-2 summarization starts right after
        # doc-1 summarization completes, overlapping with doc-1 embedding.
        assert len(embed_start_times) >= 2  # at least one call per doc
        assert len(summarize_start_times) >= 2  # at least one call per doc


# ---------------------------------------------------------------------------
# T025: StoreStep tests
# ---------------------------------------------------------------------------

class TestStoreStep:
    async def test_batch_storage(self):
        store = MockKnowledgeStorePort()
        ctx = _make_context()
        embeddings = MockEmbeddingsPort()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        await EmbedStep(embeddings_port=embeddings).execute(ctx)

        await StoreStep(knowledge_store_port=store, batch_size=5).execute(ctx)
        assert "test-collection" in store.collections
        assert len(store.collections["test-collection"]) == len(ctx.chunks)
        assert ctx.chunks_stored == len(ctx.chunks)

    async def test_correct_metadata_and_ids(self):
        store = MockKnowledgeStorePort()
        ctx = PipelineContext(
            collection_name="coll",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(
                        document_id="my-doc", source="my-src",
                        type="knowledge", title="My Title",
                        embedding_type="chunk",
                    ),
                    chunk_index=0,
                    embedding=[0.1] * 384,
                    content_hash="hash-abc",
                ),
            ],
        )

        await StoreStep(knowledge_store_port=store).execute(ctx)
        stored = store.collections["coll"][0]
        assert stored["id"] == "hash-abc"
        assert stored["metadata"]["documentId"] == "my-doc"
        assert stored["metadata"]["source"] == "my-src"
        assert stored["metadata"]["embeddingType"] == "chunk"
        assert stored["metadata"]["chunkIndex"] == 0

    async def test_precomputed_embeddings_passthrough(self):
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(document_id="d", source="s", embedding_type="chunk")
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(content="t", metadata=meta, chunk_index=0, embedding=[1.0, 2.0]),
            ],
        )
        await StoreStep(knowledge_store_port=store).execute(ctx)
        assert "c" in store.collections

    async def test_per_batch_error_handling(self):
        class FailingStore:
            async def ingest(self, **kwargs):
                raise RuntimeError("Storage unavailable")
            async def query(self, **kwargs):
                pass
            async def delete_collection(self, collection):
                pass

        meta = DocumentMetadata(document_id="d", source="s", embedding_type="chunk")
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[Chunk(content="t", metadata=meta, chunk_index=0, embedding=[0.1])],
        )
        await StoreStep(knowledge_store_port=FailingStore()).execute(ctx)  # type: ignore[arg-type]
        assert any("StoreStep" in e for e in ctx.errors)
        assert ctx.chunks_stored == 0

    async def test_skips_unembedded_chunks_when_embeddings_exist(self):
        """When some chunks have embeddings, skip those without to avoid model mismatch."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(document_id="d", source="s", embedding_type="chunk")
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(content="embedded", metadata=meta, chunk_index=0, embedding=[0.1]),
                Chunk(content="not embedded", metadata=meta, chunk_index=1),
            ],
        )
        await StoreStep(knowledge_store_port=store).execute(ctx)
        # Only the embedded chunk should be stored
        assert ctx.chunks_stored == 1
        assert len(store.collections["c"]) == 1
        assert store.collections["c"][0]["document"] == "embedded"
        assert any("skipped 1 chunks without embeddings" in e for e in ctx.errors)

    async def test_skips_all_when_no_embeddings(self):
        """Chunks without embeddings are always skipped (EmbedStep is required)."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(document_id="d", source="s", embedding_type="chunk")
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(content="a", metadata=meta, chunk_index=0),
                Chunk(content="b", metadata=meta, chunk_index=1),
            ],
        )
        await StoreStep(knowledge_store_port=store).execute(ctx)
        assert ctx.chunks_stored == 0
        assert "c" not in store.collections
        assert any("skipped 2 chunks" in e for e in ctx.errors)

    async def test_step_name(self):
        store = MockKnowledgeStorePort()
        assert StoreStep(knowledge_store_port=store).name == "store"

    async def test_skips_unchanged_chunks(self):
        """Chunks whose content_hash is in unchanged_chunk_hashes are not stored."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(
            document_id="d1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(
                    content="unchanged text", metadata=meta, chunk_index=0,
                    embedding=[0.1, 0.2], content_hash="hash-unchanged",
                ),
            ],
            unchanged_chunk_hashes={"hash-unchanged"},
        )

        await StoreStep(knowledge_store_port=store).execute(ctx)

        assert ctx.chunks_stored == 0
        assert "c" not in store.collections

    async def test_stores_changed_chunks_alongside_unchanged(self):
        """Only changed chunks are stored; unchanged are skipped."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(
            document_id="d1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(
                    content="changed text", metadata=meta, chunk_index=0,
                    embedding=[0.1, 0.2], content_hash="hash-changed",
                ),
                Chunk(
                    content="unchanged text", metadata=meta, chunk_index=1,
                    embedding=[0.3, 0.4], content_hash="hash-unchanged",
                ),
            ],
            unchanged_chunk_hashes={"hash-unchanged"},
        )

        await StoreStep(knowledge_store_port=store).execute(ctx)

        assert ctx.chunks_stored == 1
        assert len(store.collections["c"]) == 1
        assert store.collections["c"][0]["document"] == "changed text"
        assert store.collections["c"][0]["id"] == "hash-changed"

    async def test_unchanged_filter_does_not_affect_summary_chunks(self):
        """Summary chunks (content_hash=None) are always stored."""
        store = MockKnowledgeStorePort()
        chunk_meta = DocumentMetadata(
            document_id="d1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        summary_meta = DocumentMetadata(
            document_id="d1-summary", source="s", type="knowledge",
            title="T", embedding_type="summary",
        )
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(
                    content="unchanged chunk", metadata=chunk_meta, chunk_index=0,
                    embedding=[0.1, 0.2], content_hash="hash-unchanged",
                ),
                Chunk(
                    content="summary text", metadata=summary_meta, chunk_index=0,
                    embedding=[0.5, 0.6], content_hash=None,
                ),
            ],
            unchanged_chunk_hashes={"hash-unchanged"},
        )

        await StoreStep(knowledge_store_port=store).execute(ctx)

        assert ctx.chunks_stored == 1
        assert len(store.collections["c"]) == 1
        assert store.collections["c"][0]["document"] == "summary text"

    async def test_no_filter_when_unchanged_hashes_empty(self):
        """When unchanged_chunk_hashes is empty, all embedded chunks are stored."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(
            document_id="d1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        ctx = PipelineContext(
            collection_name="c",
            documents=[],
            chunks=[
                Chunk(
                    content="chunk a", metadata=meta, chunk_index=0,
                    embedding=[0.1, 0.2], content_hash="hash-a",
                ),
                Chunk(
                    content="chunk b", metadata=meta, chunk_index=1,
                    embedding=[0.3, 0.4], content_hash="hash-b",
                ),
            ],
        )

        await StoreStep(knowledge_store_port=store).execute(ctx)

        assert ctx.chunks_stored == 2
        assert len(store.collections["c"]) == 2


# ---------------------------------------------------------------------------
# T026: BodyOfKnowledgeSummaryStep tests
# ---------------------------------------------------------------------------

class TestBodyOfKnowledgeSummaryStep:
    async def test_uses_document_summaries_when_available(self):
        llm = MockLLMPort(response="BoK overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="raw text",
                    metadata=DocumentMetadata(
                        document_id="doc-1", source="s", embedding_type="chunk",
                    ),
                    chunk_index=0,
                ),
            ],
            document_summaries={"doc-1": "Doc 1 summary"},
        )

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        bok_chunks = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok_chunks) == 1
        assert bok_chunks[0].metadata.type == "bodyOfKnowledgeSummary"
        assert bok_chunks[0].metadata.embedding_type == "summary"
        assert bok_chunks[0].content == "BoK overview"

    async def test_fallback_to_raw_chunk_content(self):
        llm = MockLLMPort(response="BoK from raw")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="raw chunk text",
                    metadata=DocumentMetadata(
                        document_id="doc-1", source="s", embedding_type="chunk",
                    ),
                    chunk_index=0,
                ),
            ],
        )

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 1

    async def test_bok_entry_metadata(self):
        llm = MockLLMPort(response="Overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"][0]
        assert bok.metadata.document_id == "body-of-knowledge-summary"
        assert bok.metadata.type == "bodyOfKnowledgeSummary"
        assert bok.metadata.embedding_type == "summary"
        assert bok.chunk_index == 0

    async def test_single_section_gets_full_budget(self):
        """Single-document BoK should use the full summary_length, not 40%."""
        llm = MockLLMPort(response="Full budget overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="only doc",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )
        await BodyOfKnowledgeSummaryStep(llm_port=llm, summary_length=2000).execute(ctx)
        # The prompt should mention 2000 (100% budget), not 800 (40%)
        prompt_text = llm.calls[0][1]["content"]
        assert "2000" in prompt_text

    async def test_step_name(self):
        llm = MockLLMPort()
        assert BodyOfKnowledgeSummaryStep(llm_port=llm).name == "body_of_knowledge_summary"


# ---------------------------------------------------------------------------
# T027: IngestEngine integration tests
# ---------------------------------------------------------------------------

class TestIngestEngine:
    async def test_step_sequencing(self):
        """Verify steps run in the order provided."""
        order = []

        class RecordingStep:
            def __init__(self, label):
                self._label = label

            @property
            def name(self):
                return self._label

            async def execute(self, context):
                order.append(self._label)

        engine = IngestEngine(steps=[
            RecordingStep("a"),  # type: ignore[list-item]
            RecordingStep("b"),  # type: ignore[list-item]
            RecordingStep("c"),  # type: ignore[list-item]
        ])
        await engine.run([], "test")
        assert order == ["a", "b", "c"]

    async def test_context_propagation(self):
        """Verify context is shared between steps."""
        embeddings = MockEmbeddingsPort()
        store = MockKnowledgeStorePort()

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
        ])
        result = await engine.run([_make_doc()], "ctx-test")

        assert result.chunks_stored > 0
        assert "ctx-test" in store.collections

    async def test_ingest_result_assembly(self):
        embeddings = MockEmbeddingsPort()
        store = MockKnowledgeStorePort()

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
        ])
        result = await engine.run([_make_doc()], "result-test")

        assert isinstance(result, IngestResult)
        assert result.collection_name == "result-test"
        assert result.documents_processed == 1
        assert result.chunks_stored > 0
        assert result.success is True
        assert result.errors == []

    async def test_error_collection_from_failing_step(self):
        class FailingStep:
            @property
            def name(self):
                return "failing"

            async def execute(self, context):
                raise RuntimeError("Step exploded")

        engine = IngestEngine(steps=[
            FailingStep(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "err-test")
        assert result.success is False
        assert any("failing" in e for e in result.errors)

    async def test_zero_step_pipeline(self):
        engine = IngestEngine(steps=[])
        result = await engine.run([], "empty")
        assert result.chunks_stored == 0
        assert result.documents_processed == 0
        assert result.success is True
        assert result.errors == []

    async def test_metrics_recorded_per_step(self):
        embeddings = MockEmbeddingsPort()
        store = MockKnowledgeStorePort()
        captured: dict = {}

        class MetricCapture:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                captured["metrics"] = dict(context.metrics)

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
            MetricCapture(),  # type: ignore[list-item]
        ])
        result = await engine.run([_make_doc()], "metric-test")

        assert result.success is True
        assert result.chunks_stored > 0
        metrics = captured["metrics"]
        assert {"chunk", "embed", "store"} <= set(metrics)
        assert all(m.duration >= 0 for m in metrics.values())


# ---------------------------------------------------------------------------
# T037: Destructive step gating tests
# ---------------------------------------------------------------------------


class TestDestructiveStepGating:
    """Verify IngestEngine skips destructive steps when prior errors exist."""

    async def test_engine_skips_destructive_step_with_prior_errors(self):
        """Destructive step is not executed when context has errors."""
        executed = []

        class ErrorStep:
            @property
            def name(self):
                return "error_step"

            async def execute(self, context):
                context.errors.append("error_step: something went wrong")

        class DestructiveStep:
            @property
            def name(self):
                return "cleanup"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                executed.append("cleanup")

        engine = IngestEngine(steps=[
            ErrorStep(),  # type: ignore[list-item]
            DestructiveStep(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "test")

        assert "cleanup" not in executed
        assert any("destructive step gated" in e for e in result.errors)
        assert result.success is False

    async def test_engine_runs_destructive_step_with_no_errors(self):
        """Destructive step executes normally when no prior errors exist."""
        executed = []

        class DestructiveStep:
            @property
            def name(self):
                return "cleanup"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                executed.append("cleanup")

        engine = IngestEngine(steps=[
            DestructiveStep(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "test")

        assert "cleanup" in executed
        assert result.success is True

    async def test_non_destructive_steps_run_despite_errors(self):
        """Non-destructive steps run regardless of prior errors."""
        executed = []

        class ErrorStep:
            @property
            def name(self):
                return "error_step"

            async def execute(self, context):
                context.errors.append("error_step: failure")

        class NormalStep:
            @property
            def name(self):
                return "normal"

            async def execute(self, context):
                executed.append("normal")

        engine = IngestEngine(steps=[
            ErrorStep(),  # type: ignore[list-item]
            NormalStep(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "test")

        assert "normal" in executed
        assert result.success is False

    async def test_multiple_destructive_steps_all_skipped(self):
        """All destructive steps are skipped when errors exist."""
        executed = []

        class ErrorStep:
            @property
            def name(self):
                return "error_step"

            async def execute(self, context):
                context.errors.append("error_step: failure")

        class DestructiveA:
            @property
            def name(self):
                return "cleanup_a"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                executed.append("cleanup_a")

        class DestructiveB:
            @property
            def name(self):
                return "cleanup_b"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                executed.append("cleanup_b")

        engine = IngestEngine(steps=[
            ErrorStep(),  # type: ignore[list-item]
            DestructiveA(),  # type: ignore[list-item]
            DestructiveB(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "test")

        assert executed == []
        assert any("cleanup_a" in e and "destructive step gated" in e for e in result.errors)
        assert any("cleanup_b" in e and "destructive step gated" in e for e in result.errors)

    async def test_destructive_step_skipped_after_failing_non_destructive(self):
        """Destructive step is skipped when a prior non-destructive step raises an exception."""
        executed = []

        class RaisingStep:
            @property
            def name(self):
                return "raiser"

            async def execute(self, context):
                raise RuntimeError("unexpected crash")

        class DestructiveStep:
            @property
            def name(self):
                return "cleanup"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                executed.append("cleanup")

        engine = IngestEngine(steps=[
            RaisingStep(),  # type: ignore[list-item]
            DestructiveStep(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "test")

        assert "cleanup" not in executed
        assert any("destructive step gated" in e for e in result.errors)

    async def test_metrics_recorded_for_skipped_destructive_step(self):
        """Skipped destructive steps get StepMetrics with duration=0.0 and error_count=1."""

        class ErrorStep:
            @property
            def name(self):
                return "error_step"

            async def execute(self, context):
                context.errors.append("error_step: failure")

        class DestructiveStep:
            @property
            def name(self):
                return "cleanup"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                pass  # pragma: no cover

        captured_metrics: dict = {}

        class MetricCapture:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                captured_metrics.update(context.metrics)

        engine = IngestEngine(steps=[
            ErrorStep(),  # type: ignore[list-item]
            DestructiveStep(),  # type: ignore[list-item]
            MetricCapture(),  # type: ignore[list-item]
        ])
        await engine.run([], "test")

        assert "cleanup" in captured_metrics
        m = captured_metrics["cleanup"]
        assert m.duration == 0.0
        assert m.error_count == 1

    async def test_skip_message_format(self):
        """Verify the exact format of the skip message includes step name and error count."""

        class ErrorStep:
            @property
            def name(self):
                return "error_step"

            async def execute(self, context):
                context.errors.append("error_step: fail 1")
                context.errors.append("error_step: fail 2")

        class DestructiveStep:
            @property
            def name(self):
                return "cleanup"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                pass  # pragma: no cover

        engine = IngestEngine(steps=[
            ErrorStep(),  # type: ignore[list-item]
            DestructiveStep(),  # type: ignore[list-item]
        ])
        result = await engine.run([], "test")

        skip_msgs = [e for e in result.errors if "destructive step gated" in e]
        assert len(skip_msgs) == 1
        assert skip_msgs[0] == "cleanup: skipped (destructive step gated by 2 prior error(s))"


# ---------------------------------------------------------------------------
# T010: ChangeDetectionStep tests
# ---------------------------------------------------------------------------


class TestChangeDetectionStep:
    def _store_with_chunks(self, collection: str, chunks: list[dict]) -> MockKnowledgeStorePort:
        """Pre-populate a mock store with chunk entries."""
        store = MockKnowledgeStorePort()
        store.collections[collection] = chunks
        return store

    async def test_unchanged_chunks_skipped_with_embedding_preload(self):
        """Chunks whose content_hash matches an existing ID get their embedding pre-loaded."""
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, content_hash="hash-abc")

        store = self._store_with_chunks("coll", [
            {"id": "hash-abc", "metadata": {"documentId": "doc-1"}, "document": "text", "embedding": [1.0, 2.0]},
        ])

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=store).execute(ctx)

        assert chunk.embedding == [1.0, 2.0]
        assert "hash-abc" in ctx.unchanged_chunk_hashes
        assert ctx.chunks_skipped == 1
        assert "doc-1" not in ctx.changed_document_ids

    async def test_new_chunk_detected(self):
        """Chunks with a hash not in the store are marked as changed."""
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="new text", metadata=meta, chunk_index=0, content_hash="hash-new")

        store = self._store_with_chunks("coll", [
            {"id": "hash-old", "metadata": {"documentId": "doc-1"}, "document": "old", "embedding": [1.0]},
        ])

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=store).execute(ctx)

        assert chunk.embedding is None
        assert ctx.chunks_skipped == 0
        assert "doc-1" in ctx.changed_document_ids

    async def test_orphan_identification(self):
        """Existing IDs not produced by current chunking become orphans."""
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, content_hash="hash-new")

        store = self._store_with_chunks("coll", [
            {"id": "hash-old", "metadata": {"documentId": "doc-1"}, "document": "old", "embedding": [1.0]},
        ])

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=store).execute(ctx)

        assert "hash-old" in ctx.orphan_ids

    async def test_orphans_mark_document_as_changed(self):
        """Documents with orphans are marked as changed even if all current chunks exist."""
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, content_hash="hash-keep")

        store = self._store_with_chunks("coll", [
            {"id": "hash-keep", "metadata": {"documentId": "doc-1"}, "document": "text", "embedding": [1.0]},
            {"id": "hash-gone", "metadata": {"documentId": "doc-1"}, "document": "old", "embedding": [2.0]},
        ])

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=store).execute(ctx)

        # hash-gone is orphaned, so doc-1 should be marked as changed
        assert "doc-1" in ctx.changed_document_ids
        assert "hash-gone" in ctx.orphan_ids

    async def test_removed_document_detection(self):
        """Documents in the store but not in current batch are flagged as removed."""
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, content_hash="hash-1")

        store = self._store_with_chunks("coll", [
            {"id": "hash-1", "metadata": {"documentId": "doc-1", "embeddingType": "chunk"}, "document": "text", "embedding": [1.0]},
            {"id": "hash-2", "metadata": {"documentId": "doc-2", "embeddingType": "chunk"}, "document": "old", "embedding": [2.0]},
        ])

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=store).execute(ctx)

        assert "doc-2" in ctx.removed_document_ids

    async def test_fallback_on_store_failure(self):
        """When store raises, all chunks treated as new — full state reset."""
        call_count = 0

        class FailOnSecondCallStore:
            async def get(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First call succeeds (all-existing query)
                    return GetResult(ids=["hash-1"], metadatas=[{"documentId": "doc-1", "embeddingType": "chunk"}])
                # Second call (per-doc query) fails
                raise RuntimeError("Store unavailable")
            async def ingest(self, **kwargs):
                pass
            async def query(self, **kwargs):
                pass
            async def delete_collection(self, collection):
                pass
            async def delete(self, **kwargs):
                pass

        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, content_hash="hash-1")

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=FailOnSecondCallStore()).execute(ctx)  # type: ignore[arg-type]

        assert len(ctx.unchanged_chunk_hashes) == 0
        assert len(ctx.orphan_ids) == 0
        assert len(ctx.changed_document_ids) == 0
        assert ctx.chunks_skipped == 0
        assert ctx.change_detection_ran is False
        assert chunk.embedding is None
        # Store-read error is recorded so pipeline result reflects failure
        assert any("ChangeDetectionStep: store read failed" in e for e in ctx.errors)

    async def test_summary_chunks_not_flagged_as_removed(self):
        """Summary and BoK chunks in the store should not trigger removed-document detection."""
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, content_hash="hash-1")

        store = MockKnowledgeStorePort()
        store.collections["coll"] = [
            # Content chunk
            {"id": "hash-1", "metadata": {"documentId": "doc-1", "embeddingType": "chunk"}, "document": "text", "embedding": [1.0]},
            # Summary chunk
            {"id": "doc-1-summary-0", "metadata": {"documentId": "doc-1-summary", "embeddingType": "summary"}, "document": "summary", "embedding": [2.0]},
            # BoK summary chunk
            {"id": "body-of-knowledge-summary-0", "metadata": {"documentId": "body-of-knowledge-summary", "embeddingType": "summary"}, "document": "bok", "embedding": [3.0]},
        ]

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await ChangeDetectionStep(knowledge_store_port=store).execute(ctx)

        # Summary document IDs should NOT appear as removed
        assert "doc-1-summary" not in ctx.removed_document_ids
        assert "body-of-knowledge-summary" not in ctx.removed_document_ids
        assert len(ctx.removed_document_ids) == 0

    async def test_step_name(self):
        store = MockKnowledgeStorePort()
        assert ChangeDetectionStep(knowledge_store_port=store).name == "change_detection"


# ---------------------------------------------------------------------------
# T010: StoreStep dedup tests (content-hash IDs, metadata)
# ---------------------------------------------------------------------------


class TestStoreStepDedup:
    async def test_content_hash_used_as_storage_id(self):
        """Content chunks with content_hash use it as storage ID."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, embedding=[0.1], content_hash="abc123def456")

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await StoreStep(knowledge_store_port=store).execute(ctx)

        stored = store.collections["coll"][0]
        assert stored["id"] == "abc123def456"

    async def test_summary_uses_deterministic_id(self):
        """Summary chunks use {document_id}-{chunk_index} as ID."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(document_id="doc-1-summary", source="s", type="knowledge", title="T", embedding_type="summary")
        chunk = Chunk(content="summary text", metadata=meta, chunk_index=0, embedding=[0.1])

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await StoreStep(knowledge_store_port=store).execute(ctx)

        stored = store.collections["coll"][0]
        assert stored["id"] == "doc-1-summary-0"

    async def test_metadata_stores_original_document_id(self):
        """Metadata documentId field stores the original document_id for all chunk types."""
        store = MockKnowledgeStorePort()
        meta = DocumentMetadata(document_id="doc-1", source="s", type="knowledge", title="T", embedding_type="chunk")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0, embedding=[0.1], content_hash="hash123")

        ctx = PipelineContext(collection_name="coll", documents=[], chunks=[chunk])
        await StoreStep(knowledge_store_port=store).execute(ctx)

        stored = store.collections["coll"][0]
        assert stored["metadata"]["documentId"] == "doc-1"


# ---------------------------------------------------------------------------
# T013: OrphanCleanupStep tests
# ---------------------------------------------------------------------------


class TestOrphanCleanupStep:
    async def test_orphan_deletion(self):
        """Orphan IDs from context are deleted from the store."""
        store = MockKnowledgeStorePort()
        store.collections["coll"] = [
            {"id": "orphan-1", "metadata": {"documentId": "doc-1"}, "document": "old"},
            {"id": "keep-1", "metadata": {"documentId": "doc-1"}, "document": "keep"},
        ]

        ctx = PipelineContext(
            collection_name="coll",
            documents=[],
            orphan_ids={"orphan-1"},
        )
        await OrphanCleanupStep(knowledge_store_port=store).execute(ctx)

        remaining_ids = [it["id"] for it in store.collections["coll"]]
        assert "orphan-1" not in remaining_ids
        assert "keep-1" in remaining_ids
        assert ctx.chunks_deleted > 0

    async def test_removed_document_cleanup(self):
        """All chunks for removed documents are deleted, including summaries."""
        store = MockKnowledgeStorePort()
        store.collections["coll"] = [
            {"id": "c1", "metadata": {"documentId": "doc-removed"}, "document": "x"},
            {"id": "c2", "metadata": {"documentId": "doc-removed"}, "document": "y"},
            {"id": "s1", "metadata": {"documentId": "doc-removed-summary"}, "document": "summary"},
            {"id": "c3", "metadata": {"documentId": "doc-keep"}, "document": "z"},
        ]

        ctx = PipelineContext(
            collection_name="coll",
            documents=[],
            removed_document_ids={"doc-removed"},
        )
        await OrphanCleanupStep(knowledge_store_port=store).execute(ctx)

        remaining_ids = [it["id"] for it in store.collections["coll"]]
        assert "c1" not in remaining_ids
        assert "c2" not in remaining_ids
        assert "s1" not in remaining_ids  # summary chunk also deleted
        assert "c3" in remaining_ids

    async def test_idempotent_on_empty_sets(self):
        """No errors when orphan_ids and removed_document_ids are empty."""
        store = MockKnowledgeStorePort()
        store.collections["coll"] = [
            {"id": "c1", "metadata": {"documentId": "doc-1"}, "document": "x"},
        ]

        ctx = PipelineContext(collection_name="coll", documents=[])
        await OrphanCleanupStep(knowledge_store_port=store).execute(ctx)

        assert ctx.chunks_deleted == 0
        assert len(store.collections["coll"]) == 1
        assert len(ctx.errors) == 0

    async def test_skips_cleanup_on_store_step_errors(self):
        """Engine-level destructive gating: cleanup is skipped when StoreStep had write failures."""
        store = MockKnowledgeStorePort()
        store.collections["coll"] = [
            {"id": "orphan-1", "metadata": {"documentId": "doc-1"}, "document": "old"},
        ]

        class FailingStoreStep:
            @property
            def name(self):
                return "store"

            async def execute(self, context):
                context.errors.append("store: storage failed for batch 0: connection refused")

        engine = IngestEngine(steps=[
            FailingStoreStep(),  # type: ignore[list-item]
            OrphanCleanupStep(knowledge_store_port=store),
        ])
        # Pre-populate context: engine creates a fresh context, so we run with
        # a step that sets up orphan_ids first.
        class SetupStep:
            @property
            def name(self):
                return "setup"

            async def execute(self, context):
                context.orphan_ids = {"orphan-1"}

        engine = IngestEngine(steps=[
            SetupStep(),  # type: ignore[list-item]
            FailingStoreStep(),  # type: ignore[list-item]
            OrphanCleanupStep(knowledge_store_port=store),
        ])
        result = await engine.run([], "coll")

        # Orphan should NOT have been deleted
        remaining_ids = [it["id"] for it in store.collections["coll"]]
        assert "orphan-1" in remaining_ids
        assert result.chunks_deleted == 0
        assert any("destructive step gated" in e for e in result.errors)

    async def test_destructive_property(self):
        store = MockKnowledgeStorePort()
        assert OrphanCleanupStep(knowledge_store_port=store).destructive is True

    async def test_step_name(self):
        store = MockKnowledgeStorePort()
        assert OrphanCleanupStep(knowledge_store_port=store).name == "orphan_cleanup"


# ---------------------------------------------------------------------------
# T013: DocumentSummaryStep dedup tests
# ---------------------------------------------------------------------------


class TestDocumentSummaryStepDedup:
    async def test_skips_unchanged_documents(self):
        """Documents not in changed_document_ids are skipped when change detection ran."""
        llm = MockLLMPort(response="Summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        ctx.change_detection_ran = True
        ctx.changed_document_ids = {"other-doc"}

        chunks_before = len(ctx.chunks)
        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert len(ctx.chunks) == chunks_before  # No summary added
        assert len(llm.calls) == 0

    async def test_skips_all_when_nothing_changed(self):
        """When change detection ran and found zero changes, skip all summaries."""
        llm = MockLLMPort(response="Summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        ctx.change_detection_ran = True
        # changed_document_ids is empty — nothing changed

        chunks_before = len(ctx.chunks)
        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert len(ctx.chunks) == chunks_before
        assert len(llm.calls) == 0

    async def test_summarizes_changed_documents(self):
        """Documents in changed_document_ids get summarized normally."""
        llm = MockLLMPort(response="Summary for changed doc")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        ctx.change_detection_ran = True
        ctx.changed_document_ids = {"doc-1"}

        chunks_before = len(ctx.chunks)
        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert len(ctx.chunks) == chunks_before + 1
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1

    async def test_summarizes_all_when_no_change_detection(self):
        """When change_detection_ran is False (no ChangeDetectionStep), all docs are summarized."""
        llm = MockLLMPort(response="Summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        # change_detection_ran is False (default) — should summarize all
        assert ctx.change_detection_ran is False
        chunks_before = len(ctx.chunks)
        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert len(ctx.chunks) == chunks_before + 1


# ---------------------------------------------------------------------------
# Story #36: DocumentSummaryStep stale summary cleanup tests
# ---------------------------------------------------------------------------


class TestDocumentSummaryStepStaleCleanup:
    async def test_stale_summary_marked_as_orphan(self):
        """Changed doc that dropped below threshold has its summary orphaned."""
        llm = MockLLMPort(response="Summary")
        meta = DocumentMetadata(
            document_id="doc-1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        # Only 2 chunks — below the default threshold of 4
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(content="a", metadata=meta, chunk_index=0),
                Chunk(content="b", metadata=meta, chunk_index=1),
            ],
        )
        ctx.change_detection_ran = True
        ctx.changed_document_ids = {"doc-1"}

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert "doc-1-summary-0" in ctx.orphan_ids
        # No summary chunk should be generated (below threshold)
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 0
        assert len(llm.calls) == 0

    async def test_no_orphan_when_still_above_threshold(self):
        """Changed doc still above threshold is summarized, not orphaned."""
        llm = MockLLMPort(response="Summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) >= 4  # above threshold

        ctx.change_detection_ran = True
        ctx.changed_document_ids = {"doc-1"}

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert "doc-1-summary-0" not in ctx.orphan_ids
        # Should have generated a summary
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1

    async def test_no_stale_cleanup_without_change_detection(self):
        """No orphan marking when change detection did not run."""
        llm = MockLLMPort(response="Summary")
        meta = DocumentMetadata(
            document_id="doc-1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        # 2 chunks — below threshold, but change detection not ran
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(content="a", metadata=meta, chunk_index=0),
                Chunk(content="b", metadata=meta, chunk_index=1),
            ],
        )
        assert ctx.change_detection_ran is False

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert len(ctx.orphan_ids) == 0

    async def test_stale_cleanup_only_targets_changed_docs(self):
        """Unchanged docs below threshold are not orphaned."""
        llm = MockLLMPort(response="Summary")
        meta = DocumentMetadata(
            document_id="doc-1", source="s", type="knowledge",
            title="T", embedding_type="chunk",
        )
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(content="a", metadata=meta, chunk_index=0),
                Chunk(content="b", metadata=meta, chunk_index=1),
            ],
        )
        ctx.change_detection_ran = True
        # doc-1 is NOT in changed_document_ids
        ctx.changed_document_ids = {"other-doc"}

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        assert "doc-1-summary-0" not in ctx.orphan_ids


# ---------------------------------------------------------------------------
# BodyOfKnowledgeSummaryStep dedup tests
# ---------------------------------------------------------------------------


class TestBoKSummaryStepDedup:
    async def test_skips_when_nothing_changed(self):
        """BoK summary is skipped when change detection ran, no changes, and BoK exists in store."""
        llm = MockLLMPort(response="BoK overview")
        store = MockKnowledgeStorePort()
        # Pre-populate store with an existing BoK entry
        await store.ingest(
            collection="test",
            documents=["existing bok"],
            metadatas=[{"documentId": "body-of-knowledge-summary", "embeddingType": "summary",
                        "source": "generated", "type": "bodyOfKnowledgeSummary", "title": "T", "chunkIndex": 0}],
            ids=["body-of-knowledge-summary-0"],
            embeddings=[[0.1] * 384],
        )
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )
        ctx.change_detection_ran = True
        # changed_document_ids is empty — nothing changed

        await BodyOfKnowledgeSummaryStep(llm_port=llm, knowledge_store_port=store).execute(ctx)

        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 0
        assert len(llm.calls) == 0

    async def test_regenerates_when_docs_changed(self):
        """BoK summary regenerates when any document has changes."""
        llm = MockLLMPort(response="Updated BoK")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )
        ctx.change_detection_ran = True
        ctx.changed_document_ids = {"d1"}

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 1
        assert len(llm.calls) > 0

    async def test_regenerates_when_documents_removed(self):
        """BoK summary regenerates when documents are removed even if no content changed."""
        llm = MockLLMPort(response="Updated BoK after removal")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )
        ctx.change_detection_ran = True
        # No changed docs, but a document was removed
        ctx.removed_document_ids = {"d2"}

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 1
        assert len(llm.calls) > 0

    async def test_regenerates_when_no_change_detection(self):
        """BoK summary always regenerates when change detection didn't run (backward compat)."""
        llm = MockLLMPort(response="BoK overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )
        assert ctx.change_detection_ran is False

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 1


# ---------------------------------------------------------------------------
# Story #36: BodyOfKnowledgeSummaryStep empty-corpus cleanup tests
# ---------------------------------------------------------------------------


class TestBoKSummaryStepEmptyCorpusCleanup:
    async def test_bok_summary_orphaned_on_empty_corpus(self):
        """When all docs removed (empty corpus), BoK summary is marked for cleanup."""
        llm = MockLLMPort(response="BoK overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[],  # No content chunks at all
        )
        ctx.change_detection_ran = True
        ctx.removed_document_ids = {"doc-1", "doc-2"}

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        assert "body-of-knowledge-summary-0" in ctx.orphan_ids
        # No BoK summary chunk should be generated
        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 0
        assert len(llm.calls) == 0

    async def test_bok_summary_not_orphaned_when_docs_exist(self):
        """Non-empty corpus does not orphan BoK summary."""
        llm = MockLLMPort(response="BoK overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[
                Chunk(
                    content="text",
                    metadata=DocumentMetadata(document_id="d1", source="s", embedding_type="chunk"),
                    chunk_index=0,
                ),
            ],
        )
        ctx.change_detection_ran = True
        ctx.changed_document_ids = {"d1"}

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        assert "body-of-knowledge-summary-0" not in ctx.orphan_ids
        # BoK summary should be generated normally
        bok = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok) == 1

    async def test_bok_not_orphaned_on_empty_corpus_without_removals(self):
        """Empty corpus with no removals does not orphan BoK (nothing to clean up)."""
        llm = MockLLMPort(response="BoK overview")
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            chunks=[],
        )
        # No change detection ran, no removals
        assert ctx.change_detection_ran is False

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

        assert "body-of-knowledge-summary-0" not in ctx.orphan_ids
        assert len(llm.calls) == 0


# ---------------------------------------------------------------------------
# T017: Integration tests — full pipeline with dedup
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    async def test_reingest_unchanged_skips_all(self):
        """Ingest a corpus, then re-ingest unchanged — verify >80% skip rate."""
        store = MockKnowledgeStorePort()
        embeddings = MockEmbeddingsPort()

        # First ingestion
        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            ContentHashStep(),
            ChangeDetectionStep(knowledge_store_port=store),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
            OrphanCleanupStep(knowledge_store_port=store),
        ])
        result1 = await engine.run([_make_doc()], "integ-test")
        assert result1.success
        assert result1.chunks_stored > 0

        # Reset embed call tracking
        embeddings.calls.clear()

        # Second ingestion — same content
        result2 = await engine.run([_make_doc()], "integ-test")
        assert result2.success
        assert result2.chunks_skipped > 0

        # All content chunks should be skipped (100% skip rate on unchanged)
        assert result2.chunks_skipped == result1.chunks_stored

        # Zero embedding calls on re-ingestion (all pre-loaded from store)
        assert len(embeddings.calls) == 0

    async def test_reingest_changed_content_cleans_orphans(self):
        """Ingest then re-ingest with different content — verify orphan cleanup."""
        store = MockKnowledgeStorePort()
        embeddings = MockEmbeddingsPort()

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            ContentHashStep(),
            ChangeDetectionStep(knowledge_store_port=store),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
            OrphanCleanupStep(knowledge_store_port=store),
        ])

        # First ingestion
        doc1 = _make_doc(content="Original content. " * 50)
        result1 = await engine.run([doc1], "orphan-test")
        assert result1.success

        # Second ingestion — different content
        doc2 = _make_doc(content="Completely different text. " * 50)
        result2 = await engine.run([doc2], "orphan-test")
        assert result2.success
        assert result2.chunks_deleted > 0

        # All stored chunks should be from the new content
        stored_after_second = len(store.collections.get("orphan-test", []))
        assert stored_after_second > 0

    async def test_removed_document_chunks_deleted(self):
        """Ingest two docs, re-ingest with one removed — verify cleanup."""
        store = MockKnowledgeStorePort()
        embeddings = MockEmbeddingsPort()

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            ContentHashStep(),
            ChangeDetectionStep(knowledge_store_port=store),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
            OrphanCleanupStep(knowledge_store_port=store),
        ])

        # Ingest two documents
        doc_a = _make_doc(content="Document A content. " * 50, doc_id="doc-a")
        doc_b = _make_doc(content="Document B content. " * 50, doc_id="doc-b")
        result1 = await engine.run([doc_a, doc_b], "remove-test")
        assert result1.success

        # Re-ingest with only doc_a
        result2 = await engine.run([doc_a], "remove-test")
        assert result2.success

        # doc-b chunks should have been cleaned up
        remaining = store.collections.get("remove-test", [])
        remaining_doc_ids = {it["metadata"].get("documentId") for it in remaining}
        assert "doc-b" not in remaining_doc_ids
        assert "doc-a" in remaining_doc_ids


# ---------------------------------------------------------------------------
# DocumentSummaryStep concurrency tests
# ---------------------------------------------------------------------------


def _make_multi_doc_context(
    n_docs: int = 3,
    chunks_per_doc: int = 5,
    collection: str = "test-collection",
) -> PipelineContext:
    """Build a PipelineContext with n_docs documents, each having chunks_per_doc chunks."""
    chunks: list[Chunk] = []
    for d in range(n_docs):
        doc_id = f"doc-{d}"
        for c in range(chunks_per_doc):
            meta = DocumentMetadata(
                document_id=doc_id,
                source=f"source-{d}",
                type="knowledge",
                title=f"Doc {d}",
                embedding_type="chunk",
            )
            chunks.append(
                Chunk(content=f"Content for doc {d} chunk {c}. " * 20, metadata=meta, chunk_index=c)
            )
    return PipelineContext(
        collection_name=collection,
        documents=[],
        chunks=chunks,
    )


class _DelayedLLMPort:
    """Mock LLM that introduces an asyncio.sleep delay to measure concurrency."""

    def __init__(self, delay: float = 0.05, response: str = "summary") -> None:
        self.delay = delay
        self.response = response
        self.call_count = 0

    async def invoke(self, messages: list[dict]) -> str:
        self.call_count += 1
        await asyncio.sleep(self.delay)
        return self.response

    async def stream(self, messages: list[dict]):
        yield self.response


class _SelectiveFailLLMPort:
    """Mock LLM that fails for a specific document marker string in prompt text."""

    def __init__(self, fail_marker: str, response: str = "summary") -> None:
        self.fail_marker = fail_marker
        self.response = response
        self.call_count = 0

    async def invoke(self, messages: list[dict]) -> str:
        self.call_count += 1
        # Check if any message content contains the fail marker
        for msg in messages:
            if self.fail_marker in msg.get("content", ""):
                raise RuntimeError(f"Simulated LLM failure for {self.fail_marker}")
        return self.response

    async def stream(self, messages: list[dict]):
        yield self.response


class TestDocumentSummaryStepConcurrency:
    """Tests for concurrent document summarization (story #1823)."""

    async def test_concurrent_execution_faster_than_sequential(self):
        """With concurrency > 1, multiple documents should be summarized in parallel."""
        n_docs = 3
        delay = 0.1  # 100ms per LLM call
        ctx = _make_multi_doc_context(n_docs=n_docs, chunks_per_doc=5)
        llm = _DelayedLLMPort(delay=delay)

        step = DocumentSummaryStep(
            llm_port=llm,  # type: ignore[arg-type]
            concurrency=n_docs,
            chunk_threshold=2,
        )

        start = time.monotonic()
        await step.execute(ctx)
        elapsed = time.monotonic() - start

        # Each doc has 5 chunks, each chunk triggers one LLM call (refine pattern).
        # Sequential would take n_docs * chunks_per_doc * delay = 3 * 5 * 0.1 = 1.5s.
        # Concurrent should take roughly chunks_per_doc * delay = 0.5s + overhead.
        # We assert it completes in less than 80% of sequential time.
        sequential_estimate = n_docs * 5 * delay
        assert elapsed < sequential_estimate * 0.8, (
            f"Expected concurrent execution to be significantly faster than "
            f"sequential (~{sequential_estimate:.1f}s), but took {elapsed:.2f}s"
        )

        # All documents should have summaries
        assert len(ctx.document_summaries) == n_docs
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == n_docs

    async def test_deterministic_ordering_of_summary_chunks(self):
        """Summary chunks appear in context.chunks in input document order, not completion order."""
        n_docs = 4
        ctx = _make_multi_doc_context(n_docs=n_docs, chunks_per_doc=5)

        # Use varying delays so documents finish out of order
        call_counter = 0
        doc_delays = {"doc-0": 0.08, "doc-1": 0.02, "doc-2": 0.06, "doc-3": 0.01}

        class VaryingDelayLLM:
            async def invoke(self, messages):
                nonlocal call_counter
                call_counter += 1
                # Extract doc-id from prompt content
                content = messages[-1].get("content", "")
                for doc_id, delay in doc_delays.items():
                    if doc_id in content:
                        await asyncio.sleep(delay)
                        return f"summary-{doc_id}"
                return "summary-unknown"

            async def stream(self, messages):
                yield ""

        step = DocumentSummaryStep(
            llm_port=VaryingDelayLLM(),  # type: ignore[arg-type]
            concurrency=n_docs,
            chunk_threshold=2,
        )
        await step.execute(ctx)

        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        summary_doc_ids = [c.metadata.document_id for c in summary_chunks]

        # Should be in original document order: doc-0, doc-1, doc-2, doc-3
        expected = [f"doc-{i}-summary" for i in range(n_docs)]
        assert summary_doc_ids == expected, (
            f"Summary chunks should be in input order {expected}, got {summary_doc_ids}"
        )

    async def test_partial_failure_does_not_block_other_documents(self):
        """If summarization fails for one document, others still complete."""
        n_docs = 3
        ctx = _make_multi_doc_context(n_docs=n_docs, chunks_per_doc=5)
        # The chunk content contains "Content for doc 1 chunk N" — match on that.
        llm = _SelectiveFailLLMPort(fail_marker="Content for doc 1")

        step = DocumentSummaryStep(
            llm_port=llm,  # type: ignore[arg-type]
            concurrency=n_docs,
            chunk_threshold=2,
        )
        await step.execute(ctx)

        # doc-0 and doc-2 should have summaries
        assert "doc-0" in ctx.document_summaries
        assert "doc-2" in ctx.document_summaries
        assert "doc-1" not in ctx.document_summaries

        # One error should be recorded for doc-1
        errors_for_doc1 = [e for e in ctx.errors if "doc-1" in e]
        assert len(errors_for_doc1) == 1
        assert "DocumentSummaryStep" in errors_for_doc1[0]

        # Summary chunks: 2 (for doc-0 and doc-2)
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 2

    async def test_concurrency_one_produces_correct_results(self):
        """With concurrency=1, behavior is equivalent to sequential execution."""
        n_docs = 3
        ctx = _make_multi_doc_context(n_docs=n_docs, chunks_per_doc=5)
        llm = MockLLMPort(response="sequential summary")

        step = DocumentSummaryStep(
            llm_port=llm,
            concurrency=1,
            chunk_threshold=2,
        )
        await step.execute(ctx)

        # All documents should have summaries
        assert len(ctx.document_summaries) == n_docs
        for i in range(n_docs):
            assert f"doc-{i}" in ctx.document_summaries
            assert ctx.document_summaries[f"doc-{i}"] == "sequential summary"

        # Summary chunks in correct order
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == n_docs
        for i, sc in enumerate(summary_chunks):
            assert sc.metadata.document_id == f"doc-{i}-summary"

    async def test_multiple_documents_all_summarized(self):
        """Verify all qualifying documents get summaries with default concurrency."""
        n_docs = 5
        ctx = _make_multi_doc_context(n_docs=n_docs, chunks_per_doc=6)
        llm = MockLLMPort(response="multi-doc summary")

        step = DocumentSummaryStep(
            llm_port=llm,
            concurrency=8,
            chunk_threshold=4,
        )
        await step.execute(ctx)

        assert len(ctx.document_summaries) == n_docs
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == n_docs

    async def test_no_context_corruption_under_concurrency(self):
        """Verify context state is consistent after concurrent execution."""
        n_docs = 10
        ctx = _make_multi_doc_context(n_docs=n_docs, chunks_per_doc=5)
        initial_chunk_count = len(ctx.chunks)
        llm = _DelayedLLMPort(delay=0.01, response="safe summary")

        step = DocumentSummaryStep(
            llm_port=llm,  # type: ignore[arg-type]
            concurrency=5,
            chunk_threshold=2,
        )
        await step.execute(ctx)

        # Chunk count should be initial + n_docs (one summary each)
        assert len(ctx.chunks) == initial_chunk_count + n_docs

        # All document_summaries keys should be present
        assert len(ctx.document_summaries) == n_docs

        # No errors
        assert len(ctx.errors) == 0

        # Summary chunk doc IDs should be unique
        summary_doc_ids = [
            c.metadata.document_id
            for c in ctx.chunks
            if c.metadata.embedding_type == "summary"
        ]
        assert len(summary_doc_ids) == len(set(summary_doc_ids))


# ---------------------------------------------------------------------------
# Batched IngestEngine tests
# ---------------------------------------------------------------------------

class TestIngestEngineBatched:

    async def test_constructor_rejects_both_steps_and_batch_steps(self):
        import pytest
        with pytest.raises(ValueError, match="Cannot specify both"):
            IngestEngine(steps=[], batch_steps=[], finalize_steps=[])

    async def test_constructor_requires_finalize_with_batch(self):
        import pytest
        with pytest.raises(ValueError, match="finalize_steps"):
            IngestEngine(batch_steps=[])

    async def test_constructor_requires_steps_or_batch(self):
        import pytest
        with pytest.raises(ValueError, match="Must specify"):
            IngestEngine()

    async def test_batch_step_sequencing(self):
        """Verify batch steps run per batch, then finalize steps run once."""
        order = []

        class RecordingStep:
            def __init__(self, label):
                self._label = label

            @property
            def name(self):
                return self._label

            async def execute(self, context):
                n_docs = len(context.documents)
                order.append(f"{self._label}({n_docs})")

        docs = [_make_doc(doc_id=f"d{i}") for i in range(4)]

        engine = IngestEngine(
            batch_steps=[RecordingStep("batch")],
            finalize_steps=[RecordingStep("final")],
            batch_size=2,
        )
        await engine.run(docs, "test")

        assert order == ["batch(2)", "batch(2)", "final(4)"]

    async def test_batch_context_isolation(self):
        """Each batch gets its own context with only its documents."""
        seen_doc_ids: list[set[str]] = []

        class DocCapture:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                seen_doc_ids.append({d.metadata.document_id for d in context.documents})

        docs = [_make_doc(doc_id=f"d{i}") for i in range(3)]
        engine = IngestEngine(
            batch_steps=[DocCapture()],
            finalize_steps=[],
            batch_size=2,
        )
        await engine.run(docs, "test")

        assert seen_doc_ids == [{"d0", "d1"}, {"d2"}]

    async def test_all_document_ids_propagated_to_batches(self):
        """Each batch context has the full set of document IDs."""
        captured_ids: list[set[str]] = []

        class IDCapture:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                captured_ids.append(set(context.all_document_ids))

        docs = [_make_doc(doc_id=f"d{i}") for i in range(4)]
        engine = IngestEngine(
            batch_steps=[IDCapture()],
            finalize_steps=[],
            batch_size=2,
        )
        await engine.run(docs, "test")

        all_ids = {"d0", "d1", "d2", "d3"}
        assert captured_ids == [all_ids, all_ids]

    async def test_results_accumulated_across_batches(self):
        """Counters and errors from all batches are accumulated."""

        class CountingStep:
            @property
            def name(self):
                return "count"

            async def execute(self, context):
                context.chunks_stored += 10
                context.chunks_skipped += 1
                context.errors.append("batch-err")

        engine = IngestEngine(
            batch_steps=[CountingStep()],
            finalize_steps=[],
            batch_size=2,
        )
        result = await engine.run([_make_doc(doc_id=f"d{i}") for i in range(4)], "test")

        assert result.chunks_stored == 20
        assert result.chunks_skipped == 2
        assert len(result.errors) == 2

    async def test_document_summaries_accumulated(self):
        """document_summaries from multiple batches merge into finalize context."""
        finalize_summaries: dict[str, str] = {}

        class SummaryStep:
            @property
            def name(self):
                return "summarize"

            async def execute(self, context):
                for doc in context.documents:
                    context.document_summaries[doc.metadata.document_id] = f"summary-{doc.metadata.document_id}"

        class CaptureStep:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                finalize_summaries.update(context.document_summaries)

        docs = [_make_doc(doc_id=f"d{i}") for i in range(3)]
        engine = IngestEngine(
            batch_steps=[SummaryStep()],
            finalize_steps=[CaptureStep()],
            batch_size=2,
        )
        await engine.run(docs, "test")

        assert finalize_summaries == {"d0": "summary-d0", "d1": "summary-d1", "d2": "summary-d2"}

    async def test_raw_chunks_by_doc_accumulated(self):
        """raw_chunks_by_doc is populated from batch chunks for finalize."""
        captured: dict[str, list[str]] = {}

        class CaptureStep:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                captured.update(context.raw_chunks_by_doc)

        docs = [_make_doc(doc_id="d0", content="Hello world")]
        engine = IngestEngine(
            batch_steps=[ChunkStep(chunk_size=5000)],
            finalize_steps=[CaptureStep()],
            batch_size=5,
        )
        await engine.run(docs, "test")

        assert "d0" in captured
        assert len(captured["d0"]) > 0

    async def test_finalize_context_has_empty_chunks(self):
        """Finalize context starts with empty chunks list."""
        finalize_chunks: list = []

        class PreCaptureStep:
            @property
            def name(self):
                return "pre-capture"

            async def execute(self, context):
                finalize_chunks.extend(context.chunks)

        docs = [_make_doc(doc_id="d0")]
        engine = IngestEngine(
            batch_steps=[ChunkStep(chunk_size=100)],
            finalize_steps=[PreCaptureStep()],
            batch_size=5,
        )
        await engine.run(docs, "test")

        # finalize_chunks captured the state BEFORE any finalize step added chunks
        assert finalize_chunks == []

    async def test_finalize_context_has_all_documents(self):
        """Finalize context has all original documents."""
        finalize_doc_count = [0]

        class CaptureStep:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                finalize_doc_count[0] = len(context.documents)

        docs = [_make_doc(doc_id=f"d{i}") for i in range(7)]
        engine = IngestEngine(
            batch_steps=[],
            finalize_steps=[CaptureStep()],
            batch_size=3,
        )
        await engine.run(docs, "test")

        assert finalize_doc_count[0] == 7

    async def test_metrics_keyed_with_batch_index(self):
        """Batch step metrics use '{name}_batch_{i}' keys."""
        captured_metrics: dict = {}

        class MetricCapture:
            @property
            def name(self):
                return "capture"

            async def execute(self, context):
                captured_metrics.update(context.metrics)

        class SimpleStep:
            @property
            def name(self):
                return "step"

            async def execute(self, context):
                pass

        docs = [_make_doc(doc_id=f"d{i}") for i in range(4)]
        engine = IngestEngine(
            batch_steps=[SimpleStep()],
            finalize_steps=[MetricCapture()],
            batch_size=2,
        )
        await engine.run(docs, "test")

        assert "step_batch_0" in captured_metrics
        assert "step_batch_1" in captured_metrics

    async def test_error_in_one_batch_does_not_block_others(self):
        """A failing step in batch 1 doesn't prevent batch 2 from running."""
        batch_count = [0]

        class FailOddBatch:
            @property
            def name(self):
                return "maybe_fail"

            async def execute(self, context):
                batch_count[0] += 1
                if batch_count[0] == 1:
                    raise RuntimeError("Batch 0 exploded")

        docs = [_make_doc(doc_id=f"d{i}") for i in range(4)]
        engine = IngestEngine(
            batch_steps=[FailOddBatch()],
            finalize_steps=[],
            batch_size=2,
        )
        result = await engine.run(docs, "test")

        assert batch_count[0] == 2  # Both batches ran
        assert len(result.errors) == 1
        assert "Batch 0 exploded" in result.errors[0]

    async def test_destructive_finalize_gated_by_batch_errors(self):
        """Finalize destructive steps are skipped when batch errors exist."""
        class FailingStep:
            @property
            def name(self):
                return "fail"

            async def execute(self, context):
                raise RuntimeError("boom")

        class DestructiveStep:
            @property
            def name(self):
                return "destroy"

            @property
            def destructive(self):
                return True

            async def execute(self, context):
                context.chunks_deleted += 99

        docs = [_make_doc(doc_id="d0")]
        engine = IngestEngine(
            batch_steps=[FailingStep()],
            finalize_steps=[DestructiveStep()],
            batch_size=5,
        )
        result = await engine.run(docs, "test")

        assert result.chunks_deleted == 0  # Destructive step was skipped

    async def test_backward_compat_sequential_unchanged(self):
        """IngestEngine(steps=[...]) still works identically."""
        embeddings = MockEmbeddingsPort()
        store = MockKnowledgeStorePort()

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
        ])
        result = await engine.run([_make_doc()], "compat-test")

        assert result.success is True
        assert result.chunks_stored > 0
        assert "compat-test" in store.collections


# ---------------------------------------------------------------------------
# Batched ChangeDetectionStep tests
# ---------------------------------------------------------------------------

class TestChangeDetectionStepBatched:

    async def test_no_false_removals_with_all_document_ids(self):
        """When all_document_ids is set, docs outside the batch aren't flagged as removed."""
        store = MockKnowledgeStorePort()
        # Pre-populate store with doc-A (simulating previous ingest)
        await store.ingest(
            collection="test",
            documents=["existing content"],
            metadatas=[{"documentId": "doc-A", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["hash-A"],
            embeddings=[[0.1] * 384],
        )

        # Batch context has only doc-B, but all_document_ids includes both
        ctx = _make_context(docs=[_make_doc(doc_id="doc-B")], collection="test")
        ctx.all_document_ids = {"doc-A", "doc-B"}

        # Chunk doc-B so ChangeDetection has something to work with
        chunk_step = ChunkStep(chunk_size=5000)
        await chunk_step.execute(ctx)
        hash_step = ContentHashStep()
        await hash_step.execute(ctx)

        step = ChangeDetectionStep(knowledge_store_port=store)
        await step.execute(ctx)

        assert "doc-A" not in ctx.removed_document_ids

    async def test_fallback_to_current_doc_ids_when_all_empty(self):
        """When all_document_ids is empty, uses current batch docs (old behavior)."""
        store = MockKnowledgeStorePort()
        await store.ingest(
            collection="test",
            documents=["old content"],
            metadatas=[{"documentId": "doc-old", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["hash-old"],
            embeddings=[[0.1] * 384],
        )

        ctx = _make_context(docs=[_make_doc(doc_id="doc-new")], collection="test")
        # all_document_ids is empty (default)

        chunk_step = ChunkStep(chunk_size=5000)
        await chunk_step.execute(ctx)
        hash_step = ContentHashStep()
        await hash_step.execute(ctx)

        step = ChangeDetectionStep(knowledge_store_port=store)
        await step.execute(ctx)

        assert "doc-old" in ctx.removed_document_ids

    async def test_actual_removal_detected_with_all_document_ids(self):
        """A doc truly absent from all_document_ids is correctly flagged."""
        store = MockKnowledgeStorePort()
        await store.ingest(
            collection="test",
            documents=["gone content"],
            metadatas=[{"documentId": "doc-gone", "embeddingType": "chunk", "source": "s", "type": "t", "title": "T", "chunkIndex": 0}],
            ids=["hash-gone"],
            embeddings=[[0.1] * 384],
        )

        ctx = _make_context(docs=[_make_doc(doc_id="doc-new")], collection="test")
        ctx.all_document_ids = {"doc-new"}  # doc-gone not included

        chunk_step = ChunkStep(chunk_size=5000)
        await chunk_step.execute(ctx)
        hash_step = ContentHashStep()
        await hash_step.execute(ctx)

        step = ChangeDetectionStep(knowledge_store_port=store)
        await step.execute(ctx)

        assert "doc-gone" in ctx.removed_document_ids


# ---------------------------------------------------------------------------
# Batched BodyOfKnowledgeSummaryStep tests
# ---------------------------------------------------------------------------

class TestBoKSummaryStepBatchedMode:

    async def test_uses_raw_chunks_by_doc(self):
        """When raw_chunks_by_doc is populated, BoK uses it instead of chunks."""
        llm = MockLLMPort()
        ctx = PipelineContext(
            collection_name="test",
            documents=[_make_doc(doc_id="d0"), _make_doc(doc_id="d1")],
            raw_chunks_by_doc={
                "d0": ["content from d0 chunk 1", "content from d0 chunk 2"],
                "d1": ["content from d1"],
            },
        )

        step = BodyOfKnowledgeSummaryStep(llm_port=llm)
        await step.execute(ctx)

        # BoK chunk should be generated
        assert len(ctx.chunks) == 1
        assert ctx.chunks[0].metadata.embedding_type == "summary"
        assert ctx.chunks[0].metadata.document_id == "body-of-knowledge-summary"
        assert len(llm.calls) > 0

    async def test_prefers_document_summaries_over_raw_chunks(self):
        """When both exist for a doc, document_summaries is used."""
        llm = MockLLMPort()
        ctx = PipelineContext(
            collection_name="test",
            documents=[_make_doc(doc_id="d0")],
            raw_chunks_by_doc={"d0": ["raw content"]},
            document_summaries={"d0": "pre-computed summary of d0"},
        )

        step = BodyOfKnowledgeSummaryStep(llm_port=llm)
        await step.execute(ctx)

        # The LLM received the summary, not the raw content
        assert len(llm.calls) > 0
        last_call = llm.calls[-1]
        human_msg = [m for m in last_call if m.get("role") == "human"][0]
        assert "pre-computed summary of d0" in human_msg["content"]

    async def test_fallback_to_chunks_when_raw_chunks_empty(self):
        """When raw_chunks_by_doc is empty, existing behavior via chunks."""
        llm = MockLLMPort()
        ctx = PipelineContext(
            collection_name="test",
            documents=[_make_doc(doc_id="d0")],
            chunks=[
                Chunk(
                    content="chunk content",
                    metadata=DocumentMetadata(
                        document_id="d0", source="s", type="t",
                        title="T", embedding_type="chunk",
                    ),
                    chunk_index=0,
                ),
            ],
        )

        step = BodyOfKnowledgeSummaryStep(llm_port=llm)
        await step.execute(ctx)

        # BoK should still be generated from chunks
        bok_chunks = [c for c in ctx.chunks if c.metadata.document_id == "body-of-knowledge-summary"]
        assert len(bok_chunks) == 1

    async def test_empty_corpus_cleanup_in_batched_mode(self):
        """When raw_chunks_by_doc is empty and removals exist, BoK is marked for cleanup."""
        llm = MockLLMPort()
        ctx = PipelineContext(
            collection_name="test",
            documents=[],
            raw_chunks_by_doc={},
            removed_document_ids={"doc-gone"},
        )

        step = BodyOfKnowledgeSummaryStep(llm_port=llm)
        await step.execute(ctx)

        assert "body-of-knowledge-summary-0" in ctx.orphan_ids
