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
    embedding_type: str | None = "chunk",
) -> str:
    segments = [content, title, source, doc_type, doc_id]
    # Content with no tree position keeps its pre-043 fingerprint, so website
    # collections are not rewritten to gain nothing.
    if space_id or subspace_id or callout_id or depth:
        segments += [space_id, subspace_id, callout_id, str(depth)]
    # Only a non-chunk label is appended, so plain passages keep the
    # fingerprint they already have and are not rewritten.
    label = embedding_type or "chunk"
    if label != "chunk":
        segments.append(label)
    canonical = "\0".join(segments)
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


class TestPositionlessContentKeepsItsFingerprint:
    """Content with no tree position must not be re-fingerprinted.

    The fingerprint is the storage id, so changing it rewrites and re-embeds
    every entry and sweeps the old ids as orphans. Website ingestion gains no
    position at all, so it must not pay that cost.
    """


class TestContentHashCoversAllContentTypes:
    """Fingerprinting keys off "is this content", not the literal "chunk".

    An unfingerprinted entry is invisible to change detection: re-embedded on
    every run and never swept when its source document is deleted.
    """

    async def test_website_shaped_chunk_hashes_as_before_this_feature(self):
        """No tree position and a plain label: the fingerprint is unchanged, so
        website collections are not rewritten to gain nothing."""
        chunk = _make_chunk()
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)

        legacy_canonical = "\0".join([
            "Hello world", "Title", "src", "knowledge", "doc-1",
        ])
        legacy_hash = hashlib.sha256(
            legacy_canonical.encode("utf-8")
        ).hexdigest()
        assert chunk.content_hash == legacy_hash

    async def test_positioned_content_does_get_a_new_fingerprint(self):
        """The exemption applies only where there is genuinely no position."""
        bare = _make_chunk()
        placed = _make_chunk(space_id="sp-1", depth=0)
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[bare, placed]
        )
        await ContentHashStep().execute(ctx)
        assert bare.content_hash != placed.content_hash

    async def test_depth_alone_is_enough_to_engage_position(self):
        """A contribution at depth 3 with no ids still fingerprints distinctly."""
        bare = _make_chunk()
        deep = _make_chunk(depth=3)
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[bare, deep]
        )
        await ContentHashStep().execute(ctx)
        assert bare.content_hash != deep.content_hash

    async def test_overview_is_fingerprinted(self):
        chunk = _make_chunk(embedding_type="overview")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)
        assert chunk.content_hash is not None

    async def test_summary_is_still_not_fingerprinted(self):
        """Negative path: the widening must not overshoot.

        Summaries are derived artifacts regenerated per run, swept by their own
        naming convention rather than by content identity.
        """
        chunk = _make_chunk(embedding_type="summary")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)
        assert chunk.content_hash is None

    async def test_legacy_entry_without_an_embedding_type_is_fingerprinted(self):
        """An absent value predates the key and must count as content."""
        chunk = _make_chunk()
        chunk.metadata.embedding_type = None  # type: ignore[assignment]
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)
        assert chunk.content_hash is not None

    async def test_overview_hashing_is_deterministic_and_sensitive(self):
        a = _make_chunk(embedding_type="overview", content="same text")
        b = _make_chunk(embedding_type="overview", content="same text")
        c = _make_chunk(embedding_type="overview", content="different text")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[a, b, c]
        )
        await ContentHashStep().execute(ctx)
        assert a.content_hash == b.content_hash
        assert a.content_hash != c.content_hash


class TestLabelParticipatesInTheFingerprint:
    """The label is in the fingerprint, but only where it differs from before.

    The fingerprint is the storage id. If the label were absent from it, a
    description already in the corpus would keep its old label forever: the
    text is unchanged, so the id is unchanged, so the write is skipped and the
    new label is computed and discarded. If the label were *always* appended,
    every passage in the corpus would re-fingerprint and be rewritten for a
    label that did not change.
    """

    @staticmethod
    def _develop_hash(
        content="Hello world", title="Title", source="src",
        doc_type="knowledge", doc_id="doc-1",
    ) -> str:
        canonical = "\0".join([content, title, source, doc_type, doc_id])
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    async def test_a_plain_chunk_keeps_its_existing_fingerprint(self):
        """The blast radius must not extend to passages that did not change."""
        chunk = _make_chunk(embedding_type="chunk")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)
        assert chunk.content_hash == self._develop_hash()

    async def test_an_unlabelled_legacy_entry_keeps_its_fingerprint(self):
        chunk = _make_chunk()
        chunk.metadata.embedding_type = None  # type: ignore[assignment]
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)
        assert chunk.content_hash == self._develop_hash()

    async def test_an_overview_re_fingerprints_so_the_label_can_land(self):
        chunk = _make_chunk(embedding_type="overview")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[chunk]
        )
        await ContentHashStep().execute(ctx)
        assert chunk.content_hash != self._develop_hash()

    async def test_two_labels_of_identical_text_do_not_collide(self):
        """Otherwise one passage would silently overwrite the other."""
        as_chunk = _make_chunk(embedding_type="chunk")
        as_overview = _make_chunk(embedding_type="overview")
        ctx = PipelineContext(
            collection_name="c", documents=[], chunks=[as_chunk, as_overview]
        )
        await ContentHashStep().execute(ctx)
        assert as_chunk.content_hash != as_overview.content_hash
