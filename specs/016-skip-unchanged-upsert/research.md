# Research: Skip Upsert for Unchanged Chunks in StoreStep

**Feature Branch**: `story/1825-skip-upsert-unchanged-chunks`
**Date**: 2026-04-14

## Research Tasks

### R1: Current pipeline flow and data availability

**Context**: The ingest pipeline runs steps in order: Chunk -> ContentHash -> ChangeDetection -> Summarize -> Embed -> Store -> OrphanCleanup. StoreStep needs to know which chunks are unchanged to skip them.

**Findings**:

The existing pipeline already provides all data needed for the optimization:

1. `ContentHashStep` computes SHA-256 hashes on each chunk and sets `chunk.content_hash`.
2. `ChangeDetectionStep` queries the existing store for matching content hashes, identifies unchanged chunks, pre-loads their embeddings, and populates `context.unchanged_chunk_hashes: set[str]`.
3. `EmbedStep` already skips chunks with pre-loaded embeddings (from change detection).
4. `StoreStep` is the only step that does not yet use `unchanged_chunk_hashes` -- it upserts all chunks with embeddings regardless.

**Decision**: Filter unchanged chunks in `StoreStep.execute()` using the existing `context.unchanged_chunk_hashes` set.
**Rationale**: Zero new data structures needed. The `unchanged_chunk_hashes` set is already computed and available. The filter is a single list comprehension condition.
**Alternatives considered**: (a) Add a `changed: bool` flag to the `Chunk` dataclass -- rejected (requires modifying the dataclass, the set-based approach is simpler and already in place). (b) Filter at the pipeline engine level before calling StoreStep -- rejected (violates step encapsulation; each step should handle its own filtering logic).

---

### R2: Filter behavior for summary and BoK chunks

**Context**: Summary chunks and BoK chunks have `content_hash=None` because they are generated (not content-addressable). They must always be stored.

**Findings**:

The filter condition `c.content_hash not in context.unchanged_chunk_hashes` naturally handles `None` values because `None` is never a member of a `set[str]`. No special-casing is required.

Python behavior confirmed:
```python
>>> None in {"hash-a", "hash-b"}
False
>>> None not in {"hash-a", "hash-b"}
True
```

**Decision**: Rely on the natural `None not in set` behavior. No special case needed for summary/BoK chunks.
**Rationale**: Simpler code, fewer branches, no risk of accidentally filtering out summary chunks via a future code change that adds explicit `content_hash=None` checks.
**Alternatives considered**: (a) Explicit `if content_hash is not None and ...` guard -- rejected (redundant, adds complexity).

---

### R3: Metrics and logging accuracy

**Context**: The existing StoreStep computed `skipped = len(context.chunks) - len(storable)` which conflated chunks without embeddings and (now) unchanged chunks into a single skip count. These are different conditions with different meanings.

**Findings**:

With the new filter, the skip count must be separated into two distinct categories:
1. **No-embedding skips**: Chunks genuinely lacking embeddings (error condition, logged as error).
2. **Unchanged skips**: Chunks filtered by the unchanged hash set (normal optimization, logged at INFO).

The `no_embedding` count is computed as `sum(1 for c in context.chunks if c.embedding is None)`. The `unchanged_skipped` count is computed as `sum(1 for c in context.chunks if c.embedding is not None and c.content_hash in context.unchanged_chunk_hashes)`.

**Decision**: Separate the skip counts into two distinct computations with different log levels.
**Rationale**: Accurate metrics. Operators can distinguish between an error condition (missing embeddings) and a normal optimization (unchanged chunks skipped).
**Alternatives considered**: (a) Single combined skip message -- rejected (conflates error with optimization). (b) Add both counts to `context.errors` -- rejected (skipping unchanged chunks is not an error).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Filter mechanism | `content_hash not in unchanged_chunk_hashes` in list comprehension | Reuses existing data structure, zero new abstractions |
| Summary/BoK chunks | Rely on `None not in set` behavior | Natural Python semantics, no special case needed |
| Skip metrics | Separate no-embedding (error) from unchanged (INFO log) | Accurate reporting, distinct severity levels |
| Chunk dataclass | No modification | `unchanged_chunk_hashes` set is sufficient |
