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
    space_id: str | None = None,
    space_name: str | None = None,
    subspace_id: str | None = None,
    subspace_name: str | None = None,
    callout_id: str | None = None,
    depth: int = 0,
) -> Chunk:
    return Chunk(
        content=content,
        metadata=DocumentMetadata(
            document_id=doc_id,
            source=source,
            type=doc_type,
            title=title,
            embedding_type=embedding_type,
            space_id=space_id,
            space_name=space_name,
            subspace_id=subspace_id,
            subspace_name=subspace_name,
            callout_id=callout_id,
            depth=depth,
        ),
        chunk_index=chunk_index,
    )


def _expected_hash(
    content: str = "Hello world",
    title: str = "Title",
    source: str = "src",
    doc_type: str = "knowledge",
    doc_id: str = "doc-1",
    space_id: str = "",
    subspace_id: str = "",
    callout_id: str = "",
    depth: int = 0,
) -> str:
    canonical = "\0".join([
        content, title, source, doc_type, doc_id,
        space_id, subspace_id, callout_id, str(depth),
    ])
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


class TestContentHashPosition:
    """Position participates in the fingerprint; display names do not."""

    async def test_sensitive_to_subspace_id(self):
        """Identical text under two parents fingerprints differently.

        This is what makes a reparent rewrite the entry instead of being
        skipped as unchanged.
        """
        c1 = _make_chunk(space_id="sp-1", subspace_id="sub-a", depth=1)
        c2 = _make_chunk(space_id="sp-1", subspace_id="sub-b", depth=1)
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_space_id(self):
        c1 = _make_chunk(space_id="sp-1")
        c2 = _make_chunk(space_id="sp-2")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_callout_id(self):
        c1 = _make_chunk(space_id="sp-1", callout_id="co-1", depth=3)
        c2 = _make_chunk(space_id="sp-1", callout_id="co-2", depth=3)
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_sensitive_to_depth(self):
        c1 = _make_chunk(space_id="sp-1", subspace_id="sub-a", depth=1)
        c2 = _make_chunk(space_id="sp-1", subspace_id="sub-a", depth=2)
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash != c2.content_hash

    async def test_insensitive_to_display_names(self):
        """A rename must not re-embed a whole space — names are display-only."""
        c1 = _make_chunk(
            space_id="sp-1", space_name="Old Name",
            subspace_id="sub-a", subspace_name="Old Sub", depth=1,
        )
        c2 = _make_chunk(
            space_id="sp-1", space_name="New Name",
            subspace_id="sub-a", subspace_name="New Sub", depth=1,
        )
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[c1, c2]
        )
        await ContentHashStep().execute(ctx)
        assert c1.content_hash == c2.content_hash

    async def test_unknown_position_matches_explicit_empty(self):
        """Absent position hashes as empty — no sentinel leaks into the id."""
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[_make_chunk()]
        )
        await ContentHashStep().execute(ctx)
        assert ctx.chunks[0].content_hash == _expected_hash()
