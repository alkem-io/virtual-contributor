# Plan: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Date:** 2026-04-08

## Architecture

No architectural changes. This is a targeted optimization within `StoreStep`, one of the concrete pipeline steps in the ingest pipeline engine.

### Affected Modules

| Module | File | Change |
|--------|------|--------|
| StoreStep | `core/domain/pipeline/steps.py` | Filter unchanged chunks before upsert loop; adjust skip-count logic; add INFO log |
| Tests | `tests/core/domain/test_pipeline_steps.py` | Add tests for unchanged-chunk filtering in StoreStep |

### Modules NOT Changed

| Module | Reason |
|--------|--------|
| `Chunk` dataclass (`core/domain/ingest_pipeline.py`) | No model changes needed |
| `PipelineContext` (`core/domain/pipeline/engine.py`) | Already has `unchanged_chunk_hashes` field |
| `ChangeDetectionStep` | Already correctly populates `unchanged_chunk_hashes` |
| `EmbedStep` | Already skips chunks with pre-loaded embeddings |
| `IngestEngine` | Reads `context.chunks_stored` unchanged |

## Data Model Deltas

None. No fields added or removed from any dataclass.

## Interface Contracts

No interface changes. `StoreStep` continues to implement the `PipelineStep` protocol with the same `execute(context: PipelineContext) -> None` signature.

## Detailed Design

### Current behavior (StoreStep.execute)

```python
storable = [c for c in context.chunks if c.embedding is not None]
skipped = len(context.chunks) - len(storable)
# ... upserts ALL storable chunks
```

### New behavior

```python
# 1. Exclude unchanged chunks (content hash in unchanged set)
changed_chunks = [
    c for c in context.chunks
    if c.content_hash is None or c.content_hash not in context.unchanged_chunk_hashes
]

# 2. From the remaining, select only those with embeddings
storable = [c for c in changed_chunks if c.embedding is not None]

# 3. Count unchanged separately
unchanged_count = len(context.chunks) - len(changed_chunks)

# 4. Count missing-embedding from changed pool only
skipped = len(changed_chunks) - len(storable)

# 5. Log unchanged skip count
if unchanged_count > 0:
    logger.info("StoreStep: skipped %d unchanged chunks", unchanged_count)
```

### Why this ordering matters

- Summary chunks and BoK summary chunks have `content_hash = None`, so `c.content_hash is None` evaluates to `True` and they pass through the filter -- they are always stored.
- Content chunks identified as unchanged by `ChangeDetectionStep` have their `content_hash` in `unchanged_chunk_hashes`, so they are excluded.
- New/changed content chunks have embeddings (from `EmbedStep`) and their hash is NOT in the unchanged set, so they are stored.

## Test Strategy

| Test | Verifies |
|------|----------|
| `test_skips_unchanged_chunks` | Chunks with `content_hash` in `unchanged_chunk_hashes` are not stored |
| `test_stores_changed_chunks_with_embeddings` | Changed chunks with embeddings are stored normally |
| `test_always_stores_summary_chunks` | Summary chunks (content_hash=None) are stored even when unchanged set is populated |
| `test_chunks_stored_counter_excludes_unchanged` | `chunks_stored` only counts actually written chunks |
| `test_unchanged_not_counted_as_missing_embeddings` | The "skipped N chunks without embeddings" error does not include unchanged chunks |
| `test_backward_compat_empty_unchanged_set` | When `unchanged_chunk_hashes` is empty, behavior is identical to before |

All existing tests must continue to pass unchanged.

## Rollout Notes

- No configuration changes.
- No migration needed.
- No environment variable changes.
- Fully backward-compatible: empty `unchanged_chunk_hashes` set means no behavior change.
- Observable improvement: `chunks_stored` in `IngestResult` will be lower on incremental runs, and INFO log will report skipped unchanged count.
