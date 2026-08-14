"""Unit tests for the per-type chunk strategy table and embedding vocabulary."""

from __future__ import annotations

from core.domain.ingest_pipeline import DocumentType
from core.domain.pipeline.chunk_strategy import (
    CONTENT_EMBEDDING_TYPES,
    EMBEDDING_TYPE_CHUNK,
    EMBEDDING_TYPE_OVERVIEW,
    EMBEDDING_TYPE_SUMMARY,
    OVERVIEW_MAX_CHARS,
    is_content,
    resolve_strategy,
)


class TestResolveStrategy:
    def test_every_document_type_resolves(self):
        """Totality: no document kind can fail to resolve."""
        for doc_type in DocumentType:
            strategy = resolve_strategy(doc_type.value)
            assert strategy is not None, doc_type
            assert strategy.embedding_type in {
                EMBEDDING_TYPE_CHUNK, EMBEDDING_TYPE_OVERVIEW,
            }, doc_type

    def test_unknown_type_falls_back_to_chunk(self):
        """A type this table has never seen is chunked exactly as today."""
        for unknown in ("not-a-real-type", "", None):
            strategy = resolve_strategy(unknown)
            assert strategy.chunk_size is None
            assert strategy.chunk_overlap is None
            assert strategy.embedding_type == EMBEDDING_TYPE_CHUNK

    def test_overview_set_is_exactly_space_and_subspace(self):
        """Pins which kinds are overviews, so the set cannot widen silently.

        A knowledge base is long-form material — labelling it an overview would
        keep it whole up to the ceiling, a retrieval regression.
        """
        overview_types = {
            doc_type.value for doc_type in DocumentType
            if resolve_strategy(doc_type.value).embedding_type
            == EMBEDDING_TYPE_OVERVIEW
        }
        assert overview_types == {"space", "subspace"}

    def test_sizes_are_overrides_not_defaults(self):
        """A None size means 'inherit', so global retuning is not overridden."""
        for doc_type in ("callout", "whiteboard", "knowledge", "link", "memo"):
            strategy = resolve_strategy(doc_type)
            assert strategy.chunk_size is None, doc_type
            assert strategy.chunk_overlap is None, doc_type

    def test_post_uses_the_detail_band(self):
        assert resolve_strategy("post").chunk_size == 2000

    def test_overview_uses_the_ceiling_with_no_overlap(self):
        for doc_type in ("space", "subspace"):
            strategy = resolve_strategy(doc_type)
            assert strategy.chunk_size == OVERVIEW_MAX_CHARS, doc_type
            assert strategy.chunk_overlap == 0, doc_type

    def test_strategy_is_immutable(self):
        """The table is shared; a caller must not be able to mutate it."""
        import dataclasses

        import pytest

        strategy = resolve_strategy("post")
        with pytest.raises(dataclasses.FrozenInstanceError):
            strategy.chunk_size = 1  # type: ignore[misc]


class TestIsContent:
    def test_chunk_and_overview_are_content(self):
        assert is_content(EMBEDDING_TYPE_CHUNK)
        assert is_content(EMBEDDING_TYPE_OVERVIEW)

    def test_summary_is_not_content(self):
        """Derived artifacts are regenerated and swept by their own convention."""
        assert not is_content(EMBEDDING_TYPE_SUMMARY)

    def test_absent_value_counts_as_content(self):
        """Legacy entries predate the key.

        Treating them as non-content would make the entire pre-existing corpus
        invisible to change detection — re-embedded forever, never swept.
        """
        assert is_content(None)

    def test_unknown_value_is_not_content(self):
        """An unrecognised label is not assumed to be content."""
        assert not is_content("something-else")


class TestVocabulary:
    def test_content_types_are_exactly_chunk_and_overview(self):
        assert CONTENT_EMBEDDING_TYPES == frozenset({"chunk", "overview"})
        assert EMBEDDING_TYPE_SUMMARY not in CONTENT_EMBEDDING_TYPES

    def test_overview_ceiling_is_documented_bound(self):
        """High enough never to bind on the 500-3,000 range descriptions occupy."""
        assert OVERVIEW_MAX_CHARS == 8000
        assert OVERVIEW_MAX_CHARS > 3000
