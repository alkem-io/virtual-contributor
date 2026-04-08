# Tasks: Skip Upsert for Unchanged Chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Date:** 2026-04-08

## Task List

### T1: Add unchanged-chunk filter to StoreStep.execute()

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**Acceptance criteria:**
- The `storable` list comprehension filters out chunks where `content_hash` is in `context.unchanged_chunk_hashes`.
- A `logger.info()` call reports the count of unchanged chunks skipped.
- The "skipped N chunks without embeddings" error message accounts for intentionally skipped unchanged chunks (does not double-count them).

**Tests that prove it done:**
- `test_skips_unchanged_chunks`
- `test_backwards_compatible_empty_unchanged`

### T2: Write unit tests for unchanged-chunk skip behavior

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- `test_skips_unchanged_chunks`: A chunk with `content_hash` in `unchanged_chunk_hashes` and a pre-loaded embedding is NOT stored. `chunks_stored` is 0.
- `test_stores_changed_chunks`: A chunk with `content_hash` NOT in `unchanged_chunk_hashes` IS stored. `chunks_stored` is 1.
- `test_stores_summary_chunks_when_content_unchanged`: A summary chunk (no content_hash) is stored even when content chunks are skipped. `chunks_stored` is 1.
- `test_mixed_changed_and_unchanged`: Context with 2 unchanged content chunks, 1 changed content chunk, and 1 summary chunk. Only 2 are stored (changed + summary). `chunks_stored` is 2.
- `test_backwards_compatible_empty_unchanged`: When `unchanged_chunk_hashes` is empty, all embedded chunks are stored as before.

**Tests that prove it done:** The tests themselves, passing green.

### T3: Verify all existing tests pass

**Depends on:** T1, T2
**Acceptance criteria:**
- `poetry run pytest` passes with zero failures.
- No regressions in `TestStoreStep`, `TestStoreStepDedup`, `TestChangeDetectionStep`, `TestIngestEngine`.

### T4: Verify lint and typecheck pass

**Depends on:** T1, T2
**Acceptance criteria:**
- `poetry run ruff check core/ plugins/ tests/` passes clean.
- `poetry run pyright core/ plugins/` passes clean.
