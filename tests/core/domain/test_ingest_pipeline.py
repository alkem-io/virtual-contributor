"""Unit tests for ingest pipeline data classes."""

from __future__ import annotations

from dataclasses import replace

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

    def test_hierarchy_fields_default_to_unknown(self):
        """Every hierarchy field is optional — no existing call site changes."""
        meta = DocumentMetadata(document_id="d1", source="s1")
        assert meta.space_id is None
        assert meta.space_name is None
        assert meta.subspace_id is None
        assert meta.subspace_name is None
        assert meta.callout_id is None
        assert meta.depth == 0

    def test_hierarchy_fields_survive_dataclass_replace(self):
        """ChunkStep derives per-chunk metadata via replace() — it must carry."""
        meta = DocumentMetadata(
            document_id="d1",
            source="s1",
            space_id="sp-1",
            space_name="Root Space",
            subspace_id="sub-1",
            subspace_name="A Subspace",
            callout_id="co-1",
            depth=3,
        )
        derived = replace(meta, embedding_type="chunk")
        assert derived.embedding_type == "chunk"
        assert derived.space_id == "sp-1"
        assert derived.space_name == "Root Space"
        assert derived.subspace_id == "sub-1"
        assert derived.subspace_name == "A Subspace"
        assert derived.callout_id == "co-1"
        assert derived.depth == 3
