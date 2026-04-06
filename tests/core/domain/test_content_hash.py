"""Unit tests for ContentHashStep — determinism, field sensitivity, stability."""

from __future__ import annotations

import hashlib

from core.domain.ingest_pipeline import Chunk, DocumentMetadata
from core.domain.pipeline.engine import PipelineContext
from core.domain.pipeline.steps import ContentHashStep


def _make_chunk(
    content: str = "Hello world",
    doc_id: str = "doc-1",
    source: str = "src",
    doc_type: str = "knowledge",
    title: str = "Title",
    embedding_type: str = "chunk",
    chunk_index: int = 0,
) -> Chunk:
    return Chunk(
        content=content,
        metadata=DocumentMetadata(
            document_id=doc_id,
            source=source,
            type=doc_type,
            title=title,
            embedding_type=embedding_type,
        ),
        chunk_index=chunk_index,
    )


def _expected_hash(
    content: str = "Hello world",
    title: str = "Title",
    source: str = "src",
    doc_type: str = "knowledge",
    doc_id: str = "doc-1",
) -> str:
    canonical = "\0".join([content, title, source, doc_type, doc_id])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TestContentHashStep:
    async def test_deterministic_hash(self):
        """Same input produces the same hash across runs."""
        ctx1 = PipelineContext(
            collection_name="c", documents=[], chunks=[_make_chunk()]
        )
        ctx2 = PipelineContext(
            collection_name="c", documents=[], chunks=[_make_chunk()]
        )
        step = ContentHashStep()
        await step.execute(ctx1)
        await step.execute(ctx2)
        assert ctx1.chunks[0].content_hash == ctx2.chunks[0].content_hash

    async def test_matches_expected_sha256(self):
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[_make_chunk()]
        )
        await ContentHashStep().execute(ctx)
        assert ctx.chunks[0].content_hash == _expected_hash()

    async def test_hash_is_64_char_hex(self):
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[_make_chunk()]
        )
        await ContentHashStep().execute(ctx)
        h = ctx.chunks[0].content_hash
        assert h is not None
        assert len(h) == 64
        int(h, 16)  # valid hex

    async def test_sensitive_to_content(self):
        c1 = _make_chunk(content="aaa")
        c2 = _make_chunk(content="bbb")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_title(self):
        c1 = _make_chunk(title="A")
        c2 = _make_chunk(title="B")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_source(self):
        c1 = _make_chunk(source="s1")
        c2 = _make_chunk(source="s2")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_type(self):
        c1 = _make_chunk(doc_type="knowledge")
        c2 = _make_chunk(doc_type="space")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_document_id(self):
        c1 = _make_chunk(doc_id="d1")
        c2 = _make_chunk(doc_id="d2")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_insensitive_to_chunk_index(self):
        """chunk_index is excluded from hash per research.md R2."""
        c1 = _make_chunk(chunk_index=0)
        c2 = _make_chunk(chunk_index=5)
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash == c2.content_hash

    async def test_skips_summary_chunks(self):
        summary = _make_chunk(embedding_type="summary")
        content = _make_chunk(embedding_type="chunk")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[summary, content]
        )
        await ContentHashStep().execute(ctx)
        assert summary.content_hash is None
        assert content.content_hash is not None

    async def test_step_name(self):
        assert ContentHashStep().name == "content_hash"

    async def test_no_collision_on_field_boundary(self):
        """Null-byte separator prevents collisions from field concatenation."""
        c1 = _make_chunk(title="ab", source="cd")
        c2 = _make_chunk(title="abc", source="d")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash
