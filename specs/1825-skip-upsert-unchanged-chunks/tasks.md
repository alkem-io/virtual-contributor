# Tasks: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Date:** 2026-04-08

## Task List

### T1: Add unit tests for unchanged-chunk filtering in StoreStep (test-first)

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** None
**Acceptance criteria:**
- Add `test_skips_unchanged_chunks`: creates a context with chunks whose `content_hash` is in `unchanged_chunk_hashes`, verifies they are NOT stored and `chunks_stored` is 0.
- Add `test_stores_changed_chunks_alongside_unchanged`: mix of unchanged and changed chunks, verifies only changed ones are stored.
- Add `test_always_stores_summary_chunks_when_unchanged_set_populated`: summary chunk with `content_hash=None` is stored even when `unchanged_chunk_hashes` is non-empty.
- Add `test_unchanged_not_counted_as_missing_embeddings`: unchanged chunks with embeddings do not trigger the "skipped N chunks without embeddings" error.
- Add `test_backward_compat_empty_unchanged_set`: when `unchanged_chunk_hashes` is empty, all embedded chunks are stored (same as current behavior).
**Proves done:** Tests initially fail (red), then pass after T2.

### T2: Modify StoreStep.execute to filter unchanged chunks

**File:** `core/domain/pipeline/steps.py`
**Depends on:** T1 (tests exist to validate)
**Acceptance criteria:**
- `StoreStep.execute()` filters out chunks whose `content_hash` is not None and is present in `context.unchanged_chunk_hashes`.
- The "skipped N chunks without embeddings" error count is computed from the non-unchanged pool only.
- An INFO-level log message reports the count of unchanged chunks skipped.
- `chunks_stored` counter only increments for actually stored chunks (no change needed -- already correct by construction).
**Proves done:** All T1 tests pass green. All pre-existing tests pass green.

### T3: Run full test suite, lint, and type check

**File:** N/A (validation)
**Depends on:** T2
**Acceptance criteria:**
- `poetry run pytest` passes with 0 failures.
- `poetry run ruff check core/ plugins/ tests/` passes with 0 errors.
- `poetry run pyright core/ plugins/` passes with 0 errors.
**Proves done:** Clean CI-equivalent run.
