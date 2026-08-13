"""Per-document-type chunking strategy and the embedding-type vocabulary.

This lives apart from ``steps.py`` for two reasons. It is imported by four
distinct pipeline steps, so putting it beside any one of them would be
arbitrary; and ``steps.py`` is the busiest merge surface in the repo, so a new
table added inline there would collide with every other in-flight change.

The embedding type is not a decorative label. Six pipeline behaviours branch on
it — content fingerprinting, both halves of change detection, storage identity,
orphan cleanup, and the corpus-summary input set. Each of those asks the same
question, "is this primary content?", and each historically spelled it as
``== "chunk"``. Introducing a second content label without widening those tests
would leave the new passages unfingerprinted, invisible to change detection,
re-embedded on every run, and never swept when their source is deleted. So the
question is asked once, here, through :func:`is_content`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Primary content, split from a source document.
EMBEDDING_TYPE_CHUNK = "chunk"

#: Primary content that is a broad, self-contained orienting statement — a
#: space or subspace description. Kept whole so it answers as a unit.
EMBEDDING_TYPE_OVERVIEW = "overview"

#: A derived artifact regenerated from other content, never a source document.
EMBEDDING_TYPE_SUMMARY = "summary"

#: The embedding types that represent primary content. Summaries are excluded:
#: they are regenerated per run and swept by their own naming convention.
CONTENT_EMBEDDING_TYPES: frozenset[str] = frozenset(
    {EMBEDDING_TYPE_CHUNK, EMBEDDING_TYPE_OVERVIEW}
)

#: Upper bound on a passage kept whole. Past this an embedding stops
#: representing the text usefully, so an unbounded overview would defeat the
#: purpose of keeping it whole in exactly the pathological case. Set far above
#: the 500–3,000 characters a description actually occupies, so it never binds
#: in practice.
OVERVIEW_MAX_CHARS = 8000


def is_content(embedding_type: str | None) -> bool:
    """Whether an entry is primary content rather than a derived artifact.

    An absent or ``None`` value counts as content. Entries written before the
    embedding type existed carry no such key, and treating them as non-content
    would make the entire legacy corpus invisible to change detection — every
    one of those entries would be re-embedded forever and never swept.
    """
    if embedding_type is None:
        return True
    return embedding_type in CONTENT_EMBEDDING_TYPES


@dataclass(frozen=True)
class ChunkStrategy:
    """How one kind of document should be split and labelled.

    ``chunk_size`` and ``chunk_overlap`` are **overrides**: ``None`` means
    "whatever the step was constructed with". The table must never restate a
    default, so that retuning the global size composes with this table instead
    of being silently overridden by it.
    """

    chunk_size: int | None
    chunk_overlap: int | None
    embedding_type: str


#: Applied to documents with no entry of their own, and to any type this table
#: has never heard of. A table miss is normal, never an error.
_DEFAULT_STRATEGY = ChunkStrategy(
    chunk_size=None, chunk_overlap=None, embedding_type=EMBEDDING_TYPE_CHUNK
)

#: Keyed by ``DocumentType`` value. ``knowledge`` is deliberately absent: a
#: knowledge base is long-form material, not a short orienting description, so
#: keeping it whole would be a retrieval regression rather than a gain.
_STRATEGIES: dict[str, ChunkStrategy] = {
    # A description is a self-contained statement of what a space is for; split
    # in half, neither half answers anything. Zero overlap because there is
    # nothing to bridge when the text is one passage.
    "space": ChunkStrategy(OVERVIEW_MAX_CHARS, 0, EMBEDDING_TYPE_OVERVIEW),
    "subspace": ChunkStrategy(OVERVIEW_MAX_CHARS, 0, EMBEDDING_TYPE_OVERVIEW),
    # Already shorter than any plausible size — stated explicitly so the intent
    # survives a future retuning rather than depending on the number.
    "callout": ChunkStrategy(None, None, EMBEDDING_TYPE_CHUNK),
    # Long-form contributions: the band the benchmarks favour for detail.
    "post": ChunkStrategy(2000, None, EMBEDDING_TYPE_CHUNK),
    # Sizing entry only. Extracting structure from a whiteboard is a separate
    # concern with its own failure modes and is out of scope here.
    "whiteboard": ChunkStrategy(None, None, EMBEDDING_TYPE_CHUNK),
}


def resolve_strategy(document_type: str | None) -> ChunkStrategy:
    """Return the strategy for a document type. Total over every input.

    Unknown types, the empty string and ``None`` all resolve to the default, so
    a document kind this table has never seen is chunked exactly as it is
    today rather than failing ingestion.
    """
    if not document_type:
        return _DEFAULT_STRATEGY
    return _STRATEGIES.get(document_type, _DEFAULT_STRATEGY)
