# Tasks: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Date:** 2026-04-08

---

## Task List

### T1: Modify StoreStep to filter out unchanged chunks
**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**AC:** StoreStep.execute() excludes chunks whose content_hash is in context.unchanged_chunk_hashes. Summary/BoK chunks (content_hash=None) always pass through. Unchanged count logged at INFO level.
**Tests:** T2 tests validate this behavior.

### T2: Add unit tests for unchanged-chunk filtering
**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**AC:** Four new test methods in TestStoreStep:
- test_skips_unchanged_chunks
- test_stores_changed_chunks_alongside_unchanged
- test_summary_chunks_always_stored_despite_unchanged_hashes
- test_backward_compat_no_change_detection
**Tests:** All four pass and cover the filtering logic paths.

### T3: Verify all existing tests pass
**Depends on:** T1, T2
**AC:** `poetry run pytest` exits 0 with no failures. All existing StoreStep, ChangeDetection, IngestEngine, and pipeline integration tests pass.
**Tests:** Full test suite green.

### T4: Verify lint, typecheck, build pass
**Depends on:** T1, T2
**AC:** `poetry run ruff check core/ plugins/ tests/` and `poetry run pyright core/ plugins/` both exit 0.
**Tests:** Static analysis clean.
