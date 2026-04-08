# Plan: Skip Upsert for Unchanged Chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Date:** 2026-04-08

## Architecture

This is a single-file change in the pipeline step layer. No new modules, adapters, ports, or configuration are required.

### Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` (StoreStep) | Add filter to exclude unchanged content chunks from upsert |
| `tests/core/domain/test_pipeline_steps.py` | Add tests for unchanged-chunk skip behavior |

### No Changes To

- `core/domain/pipeline/engine.py` -- PipelineContext already has `unchanged_chunk_hashes`
- `core/domain/ingest_pipeline.py` -- No new fields on Chunk or IngestResult
- `core/ports/` -- No port changes
- `core/adapters/` -- No adapter changes
- `plugins/` -- No plugin changes

## Data Model Deltas

None. All required data structures already exist:
- `PipelineContext.unchanged_chunk_hashes: set[str]` -- populated by ChangeDetectionStep
- `Chunk.content_hash: str | None` -- populated by ContentHashStep

## Interface Contracts

No interface changes. `StoreStep.execute(context: PipelineContext) -> None` signature is unchanged.

## Implementation Detail

Current `StoreStep.execute()` line 458:
```python
storable = [c for c in context.chunks if c.embedding is not None]
```

New logic:
```python
storable = [
    c for c in context.chunks
    if c.embedding is not None
    and c.content_hash not in context.unchanged_chunk_hashes
]
```

This works because:
1. Content chunks with `content_hash` in `unchanged_chunk_hashes` are skipped (the optimization).
2. Summary chunks have `content_hash = None`, and `None not in set()` is `True`, so summaries always pass through.
3. When `unchanged_chunk_hashes` is empty (no change detection ran), no chunks are skipped -- backwards compatible.

Additionally:
- Compute `unchanged_skipped` count separately: chunks that have embeddings but are in `unchanged_chunk_hashes`.
- Log unchanged skip count at INFO level.
- Compute `no_embedding` count as chunks without embeddings (genuine failures), excluding the unchanged ones.
- Only report the no-embedding count in `context.errors` if > 0, preserving existing error-reporting behavior for genuine missing-embedding cases.

## Test Strategy

| Test | Purpose |
|------|---------|
| `test_skips_unchanged_chunks` | Chunks with content_hash in unchanged_chunk_hashes are not stored |
| `test_stores_changed_chunks` | Chunks with content_hash NOT in unchanged_chunk_hashes are stored normally |
| `test_stores_summary_chunks_when_content_unchanged` | Summary chunks (no content_hash) are stored even when content chunks are unchanged |
| `test_mixed_changed_and_unchanged` | Mix of changed, unchanged, and summary chunks -- only changed + summaries stored |
| `test_backwards_compatible_empty_unchanged` | When unchanged_chunk_hashes is empty, all embedded chunks stored (existing behavior) |

## Rollout Notes

- Zero-config change. Deployed automatically with next release.
- No migration needed. Existing ChromaDB data is unaffected.
- Observable improvement: reduced `chunks_stored` count in IngestResult when content is unchanged.
- Log message at INFO level: "StoreStep: skipped N unchanged chunks".
