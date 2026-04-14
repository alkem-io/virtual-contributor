# Plan: Skip upsert for unchanged chunks in StoreStep

**Story:** #1825

## Architecture

No architectural changes. This is a targeted optimization within the existing pipeline step framework. The change modifies `StoreStep` to use existing change detection data from `PipelineContext.unchanged_chunk_hashes` that is already populated by `ChangeDetectionStep`.

## Affected Modules

| Module | File | Change |
|--------|------|--------|
| StoreStep | `core/domain/pipeline/steps.py` | Filter unchanged chunks before upsert; add skip logging |
| Tests | `tests/core/domain/test_pipeline_steps.py` | Add tests for skip-unchanged behavior |

## Data Model Deltas

None. All required data structures already exist:
- `PipelineContext.unchanged_chunk_hashes: set[str]` -- already populated by `ChangeDetectionStep`
- `Chunk.content_hash: str | None` -- already computed by `ContentHashStep`

## Interface Contracts

No changes to any port or protocol. `StoreStep` continues to call `KnowledgeStorePort.ingest()` with the same signature, just with fewer items.

## Implementation Detail

In `StoreStep.execute()`:
1. After filtering chunks with embeddings (existing logic), add a second filter to exclude chunks whose `content_hash` is present in `context.unchanged_chunk_hashes`.
2. Log the count of unchanged chunks skipped at INFO level.
3. The unchanged chunk count is NOT added to `context.errors` (it is not an error condition).

Filter logic:
```python
storable = [
    c for c in context.chunks
    if c.embedding is not None
    and c.content_hash not in context.unchanged_chunk_hashes
]
```

Key insight: `context.unchanged_chunk_hashes` is a `set[str]`. `Chunk.content_hash` is `str | None`. Since `None` is never in the set, summary and BoK chunks (which have `content_hash=None`) pass the filter naturally.

## Test Strategy

1. **test_skips_unchanged_chunks**: Create a context with unchanged_chunk_hashes populated and chunks with matching content_hash. Verify those chunks are not stored.
2. **test_stores_changed_chunks_alongside_unchanged**: Mix of changed and unchanged chunks. Verify only changed ones are stored.
3. **test_unchanged_filter_does_not_affect_summary_chunks**: Summary chunks (content_hash=None) should always be stored even when unchanged_chunk_hashes is populated.
4. **test_no_filter_when_unchanged_hashes_empty**: When unchanged_chunk_hashes is empty, all embedded chunks are stored (backward compatibility).

## Rollout Notes

- No migration needed. The change is purely in-memory pipeline logic.
- No configuration changes.
- Backward compatible: when `unchanged_chunk_hashes` is empty (no change detection or first run), behavior is identical to current code.
