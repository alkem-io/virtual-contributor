# Plan: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Date:** 2026-04-08

---

## Architecture

No architectural changes. This is a localized optimization inside an existing pipeline step. The pipeline engine, step protocol, and context data model remain unchanged.

### Affected Modules

| Module | File | Change |
|--------|------|--------|
| StoreStep | `core/domain/pipeline/steps.py` (lines 442-505) | Add filter to exclude unchanged chunks from upsert |
| Tests | `tests/core/domain/test_pipeline_steps.py` | Add tests for unchanged-chunk filtering in StoreStep |

### Data Model Deltas

None. `PipelineContext.unchanged_chunk_hashes` already exists and is populated by `ChangeDetectionStep`. No new fields needed.

### Interface Contracts

No changes to any port or protocol. `StoreStep` continues to satisfy `PipelineStep` protocol. `KnowledgeStorePort.ingest()` signature unchanged.

## Detailed Design

### StoreStep.execute() modifications

Current flow:
```
storable = [c for c in context.chunks if c.embedding is not None]
# upserts ALL storable chunks
```

New flow:
```
all_with_embeddings = [c for c in context.chunks if c.embedding is not None]
storable = [
    c for c in all_with_embeddings
    if c.content_hash is None                              # summaries, BoK -- always store
    or c.content_hash not in context.unchanged_chunk_hashes  # new/changed
]
unchanged_count = len(all_with_embeddings) - len(storable)
# log unchanged_count at INFO level
# upsert only storable chunks
# chunks without embeddings still logged as errors (existing behavior)
```

Key invariants:
- `content_hash is None` => always stored (summary chunks, BoK overview)
- `content_hash not in unchanged_chunk_hashes` => new or changed chunk, store it
- `content_hash in unchanged_chunk_hashes` => skip, already in ChromaDB with identical data

### Logging

Add an INFO log when `unchanged_count > 0`:
```
logger.info("StoreStep: skipped %d unchanged chunks", unchanged_count)
```

No error entry for skipped unchanged chunks.

## Test Strategy

### New Tests (in TestStoreStep class)

1. **test_skips_unchanged_chunks**: Pre-populate `unchanged_chunk_hashes` with a content hash. Verify that chunk is not stored and `chunks_stored` does not count it.

2. **test_stores_changed_chunks_alongside_unchanged**: Mix of unchanged and changed chunks. Verify only changed chunks are stored.

3. **test_summary_chunks_always_stored**: Summary chunk (content_hash=None) with `unchanged_chunk_hashes` populated. Verify summary is stored.

4. **test_no_regression_without_change_detection**: Empty `unchanged_chunk_hashes` (no change detection). All embedded chunks stored as before.

### Existing Tests

All existing StoreStep tests should pass without modification because they do not populate `unchanged_chunk_hashes`.

## Rollout Notes

- Zero-config change. The optimization activates automatically when `ChangeDetectionStep` runs before `StoreStep` (which is the current pipeline configuration).
- If change detection is disabled or fails, `unchanged_chunk_hashes` remains empty and all chunks are stored (backward compatible).
