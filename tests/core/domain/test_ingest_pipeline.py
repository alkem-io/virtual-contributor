"""Unit tests for ingest pipeline data classes."""

from __future__ import annotations

from core.domain.ingest_pipeline import (
    Chunk,
    Document,
    DocumentMetadata,
    DocumentType,
    IngestResult,
)


class TestDataClasses:
    def test_document_metadata_defaults(self):
        meta = DocumentMetadata(document_id="d1", source="s1")
        assert meta.type == "knowledge"
        assert meta.title == ""
        assert meta.embedding_type == "knowledge"

    def test_chunk_creation(self):
        meta = DocumentMetadata(document_id="d1", source="s1")
        chunk = Chunk(content="text", metadata=meta, chunk_index=0)
        assert chunk.content == "text"
        assert chunk.summary is None
        assert chunk.embedding is None

    def test_document_creation(self):
        meta = DocumentMetadata(document_id="d1", source="s1")
        doc = Document(content="full text", metadata=meta)
        assert doc.chunks is None

    def test_ingest_result_defaults(self):
        result = IngestResult(
            collection_name="test",
            documents_processed=1,
            chunks_stored=5,
        )
        assert result.success is True
        assert result.errors == []

    def test_document_type_enum(self):
        assert DocumentType.KNOWLEDGE == "knowledge"
        assert DocumentType.SPACE == "space"
        assert DocumentType.NONE == "none"
