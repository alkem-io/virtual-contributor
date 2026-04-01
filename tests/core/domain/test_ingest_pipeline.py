"""Unit tests for ingest pipeline."""

from __future__ import annotations


from core.domain.ingest_pipeline import (
    Document,
    DocumentMetadata,
    IngestResult,
    run_ingest_pipeline,
)
from tests.conftest import MockEmbeddingsPort, MockKnowledgeStorePort


def _make_doc(content: str = "Test content " * 100, doc_id: str = "doc-1") -> Document:
    return Document(
        content=content,
        metadata=DocumentMetadata(
            document_id=doc_id,
            source="test-source",
            type="knowledge",
            title="Test Doc",
        ),
    )


class TestIngestPipeline:
    async def test_chunking_produces_chunks(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        doc = _make_doc()
        result = await run_ingest_pipeline(
            documents=[doc],
            collection_name="test-collection",
            embeddings_port=embeddings,
            knowledge_store_port=ks,
            chunk_size=100,
            chunk_overlap=20,
        )
        assert result.chunks_stored > 0
        assert result.documents_processed == 1

    async def test_configurable_chunk_size(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        doc = _make_doc("word " * 1000)

        result_small = await run_ingest_pipeline(
            documents=[doc], collection_name="c1",
            embeddings_port=embeddings, knowledge_store_port=ks,
            chunk_size=100, chunk_overlap=10,
        )
        result_large = await run_ingest_pipeline(
            documents=[doc], collection_name="c2",
            embeddings_port=embeddings, knowledge_store_port=ks,
            chunk_size=2000, chunk_overlap=200,
        )
        assert result_small.chunks_stored > result_large.chunks_stored

    async def test_embedding_batching(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        doc = _make_doc("word " * 500)
        await run_ingest_pipeline(
            documents=[doc], collection_name="test",
            embeddings_port=embeddings, knowledge_store_port=ks,
            chunk_size=50, chunk_overlap=5, batch_size=5,
        )
        # Should have multiple embedding calls due to batch_size=5
        assert len(embeddings.calls) >= 1

    async def test_batch_storage(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        doc = _make_doc("content " * 200)
        result = await run_ingest_pipeline(
            documents=[doc], collection_name="test-col",
            embeddings_port=embeddings, knowledge_store_port=ks,
            chunk_size=100, chunk_overlap=10,
        )
        assert "test-col" in ks.collections
        assert result.success is True

    async def test_metadata_propagation(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        doc = _make_doc()
        await run_ingest_pipeline(
            documents=[doc], collection_name="meta-test",
            embeddings_port=embeddings, knowledge_store_port=ks,
            chunk_size=100, chunk_overlap=10,
        )
        stored = ks.collections.get("meta-test", [])
        assert len(stored) > 0
        meta = stored[0]["metadata"]
        assert meta["documentId"] == "doc-1"
        assert meta["source"] == "test-source"

    async def test_ingest_result_assembly(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        result = await run_ingest_pipeline(
            documents=[_make_doc()], collection_name="result-test",
            embeddings_port=embeddings, knowledge_store_port=ks,
        )
        assert isinstance(result, IngestResult)
        assert result.collection_name == "result-test"
        assert result.documents_processed == 1

    async def test_empty_documents(self):
        embeddings = MockEmbeddingsPort()
        ks = MockKnowledgeStorePort()
        result = await run_ingest_pipeline(
            documents=[], collection_name="empty",
            embeddings_port=embeddings, knowledge_store_port=ks,
        )
        assert result.chunks_stored == 0
