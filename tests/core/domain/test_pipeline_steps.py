"""Unit tests for all pipeline steps and IngestEngine."""

from __future__ import annotations

from core.domain.ingest_pipeline import Chunk, Document, DocumentMetadata, IngestResult
from core.domain.pipeline.engine import IngestEngine, PipelineContext
from core.domain.pipeline.steps import (
    BodyOfKnowledgeSummaryStep,
    ChunkStep,
    DocumentSummaryStep,
    EmbedStep,
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
                ),
            ],
        )

        await StoreStep(knowledge_store_port=store).execute(ctx)
        stored = store.collections["coll"][0]
        assert stored["id"] == "my-doc-0"
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
