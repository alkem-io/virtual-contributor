"""Unit tests for all pipeline steps and IngestEngine."""

from __future__ import annotations

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

    async def test_incremental_embedding_embeds_chunks_after_summary(self):
        """With embeddings_port, content chunks and summary chunk are embedded."""
        llm = MockLLMPort(response="Generated summary")
        embeddings = MockEmbeddingsPort()
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)
        assert len(ctx.chunks) > 3

        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=embeddings,
        ).execute(ctx)

        # All content chunks for the document should be embedded
        content_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "chunk"]
        for chunk in content_chunks:
            assert chunk.embedding is not None, (
                f"Content chunk {chunk.chunk_index} should have embedding"
            )

        # Summary chunk should also be embedded
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1
        assert summary_chunks[0].embedding is not None

    async def test_no_incremental_embedding_without_port(self):
        """Without embeddings_port, chunks should NOT have embeddings."""
        llm = MockLLMPort(response="Generated summary")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(llm_port=llm).execute(ctx)

        content_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "chunk"]
        for chunk in content_chunks:
            assert chunk.embedding is None

        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1
        assert summary_chunks[0].embedding is None

    async def test_incremental_embedding_error_resilience(self):
        """Failing embeddings_port: summarization succeeds, error recorded."""
        class FailingEmbeddings:
            async def embed(self, texts):
                raise RuntimeError("Embedding service down")

        llm = MockLLMPort(response="Summary despite embed failure")
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=FailingEmbeddings(),  # type: ignore[arg-type]
        ).execute(ctx)

        # Summarization should still succeed
        assert "doc-1" in ctx.document_summaries
        summary_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "summary"]
        assert len(summary_chunks) == 1

        # Error should be recorded
        assert any("incremental embedding failed" in e for e in ctx.errors)

        # Chunks should NOT have embeddings (failed)
        content_chunks = [c for c in ctx.chunks if c.metadata.embedding_type == "chunk"]
        for chunk in content_chunks:
            assert chunk.embedding is None

    async def test_incremental_embedding_skipped_by_embed_step(self):
        """EmbedStep should only embed chunks NOT already embedded by DocumentSummaryStep."""
        llm = MockLLMPort(response="Summary text")
        embeddings = MockEmbeddingsPort()
        ctx = _make_context()
        await ChunkStep(chunk_size=100, chunk_overlap=10).execute(ctx)

        # Run DocumentSummaryStep with embeddings — this embeds all doc-1 chunks
        await DocumentSummaryStep(
            llm_port=llm, embeddings_port=embeddings,
        ).execute(ctx)

        # Record how many embed calls were made by DocumentSummaryStep
        calls_after_summary = len(embeddings.calls)

        # Now run EmbedStep — should have nothing to embed (all chunks already done)
        await EmbedStep(embeddings_port=embeddings).execute(ctx)

        # EmbedStep should NOT have made any additional embed calls
        assert len(embeddings.calls) == calls_after_summary


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

    async def test_incremental_embedding_full_pipeline(self):
        """Full pipeline with incremental embedding: all chunks stored correctly."""
        llm = MockLLMPort(response="Document summary")
        embeddings = MockEmbeddingsPort()
        store = MockKnowledgeStorePort()

        # Two documents: one large (will be summarized) and one small (below threshold)
        large_doc = _make_doc(content="Large content. " * 200, doc_id="large-doc")
        small_doc = _make_doc(content="Small.", doc_id="small-doc")

        engine = IngestEngine(steps=[
            ChunkStep(chunk_size=100, chunk_overlap=10),
            DocumentSummaryStep(
                llm_port=llm,
                embeddings_port=embeddings,
            ),
            BodyOfKnowledgeSummaryStep(llm_port=llm),
            EmbedStep(embeddings_port=embeddings),
            StoreStep(knowledge_store_port=store),
        ])
        result = await engine.run([large_doc, small_doc], "incr-embed-test")

        assert result.success is True
        assert result.chunks_stored > 0

        # All stored chunks should have embeddings
        stored = store.collections.get("incr-embed-test", [])
        assert len(stored) > 0
        for entry in stored:
            assert entry.get("embedding") is not None, (
                f"Stored chunk {entry['id']} should have an embedding"
            )


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
        """Cleanup is skipped when StoreStep had write failures."""
        store = MockKnowledgeStorePort()
        store.collections["coll"] = [
            {"id": "orphan-1", "metadata": {"documentId": "doc-1"}, "document": "old"},
        ]

        ctx = PipelineContext(
            collection_name="coll",
            documents=[],
            orphan_ids={"orphan-1"},
            errors=["StoreStep: storage failed for batch 0: connection refused"],
        )
        await OrphanCleanupStep(knowledge_store_port=store).execute(ctx)

        # Orphan should NOT have been deleted
        remaining_ids = [it["id"] for it in store.collections["coll"]]
        assert "orphan-1" in remaining_ids
        assert ctx.chunks_deleted == 0
        assert any("skipped cleanup" in e for e in ctx.errors)

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
# BodyOfKnowledgeSummaryStep dedup tests
# ---------------------------------------------------------------------------


class TestBoKSummaryStepDedup:
    async def test_skips_when_nothing_changed(self):
        """BoK summary is skipped when change detection ran and found no changes."""
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
        # changed_document_ids is empty — nothing changed

        await BodyOfKnowledgeSummaryStep(llm_port=llm).execute(ctx)

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
