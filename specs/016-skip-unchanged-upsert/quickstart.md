# Quickstart: Skip Upsert for Unchanged Chunks in StoreStep

**Feature Branch**: `story/1825-skip-upsert-unchanged-chunks`
**Date**: 2026-04-14

## What This Feature Does

Optimizes the ingest pipeline by skipping ChromaDB upserts for chunks that have not changed since the last ingest. On incremental updates where most content is unchanged, this reduces ChromaDB I/O by up to 98%.

The change is internal to `StoreStep` and requires no configuration changes, no new environment variables, and no migration.

## How It Works

The existing pipeline already identifies unchanged chunks:

1. `ContentHashStep` computes SHA-256 hashes for each chunk
2. `ChangeDetectionStep` compares hashes against the store, marks unchanged ones, and pre-loads their embeddings
3. `EmbedStep` skips chunks with pre-loaded embeddings
4. **NEW**: `StoreStep` now skips chunks whose `content_hash` is in `unchanged_chunk_hashes`

## Quick Verification

### 1. Run the test suite

```bash
# Run the specific StoreStep tests
poetry run pytest tests/core/domain/test_pipeline_steps.py -k "TestStoreStep" -v

# Expected output includes:
#   test_skips_unchanged_chunks PASSED
#   test_stores_changed_chunks_alongside_unchanged PASSED
#   test_unchanged_filter_does_not_affect_summary_chunks PASSED
#   test_no_filter_when_unchanged_hashes_empty PASSED
```

### 2. Verify in logs during incremental ingest

```bash
# Run an ingest plugin
export PLUGIN_TYPE=ingest-space
poetry run python main.py

# On incremental ingest (second run, no content changes), look for:
#   INFO: StoreStep: skipped 100 unchanged chunks
#   (where 100 = total chunk count from previous ingest)
```

### 3. Verify backward compatibility

When change detection has not run (e.g., first ingest or change detection disabled), `unchanged_chunk_hashes` is empty and StoreStep stores all embedded chunks -- identical to previous behavior.

## Files Changed

| File | Change |
|------|--------|
| `core/domain/pipeline/steps.py` | Filter unchanged chunks in `StoreStep.execute()`; separate no-embedding and unchanged skip counts |
| `tests/core/domain/test_pipeline_steps.py` | 4 new tests for skip-unchanged behavior |

## Contracts

No external interface changes:
- **KnowledgeStorePort**: Unchanged (StoreStep calls `ingest()` with fewer items)
- **PluginContract**: Unchanged
- **Event schemas**: Unchanged
- **PipelineContext**: Unchanged (uses existing `unchanged_chunk_hashes` field)
