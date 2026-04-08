# Tasks: Handle Empty Corpus Re-ingestion

**Story:** #35
**Date:** 2026-04-08

## Task List

### T1: Modify IngestSpacePlugin to run cleanup on empty fetch
**File:** `plugins/ingest_space/plugin.py`
**Depends on:** None
**Acceptance criteria:**
- The `if not documents:` block no longer returns early.
- Instead, it logs an info message and runs a cleanup-only pipeline: `IngestEngine([ChangeDetectionStep, OrphanCleanupStep]).run([], collection_name)`.
- The result is constructed from the pipeline outcome (success if no errors, failure otherwise).
- The exception handler (`except Exception`) remains unchanged, preserving failure behavior on fetch errors.
**Test:** T3

### T2: Modify IngestWebsitePlugin to run cleanup on empty fetch
**File:** `plugins/ingest_website/plugin.py`
**Depends on:** None
**Acceptance criteria:**
- The `if not documents:` block no longer returns early with `error="No content extracted"`.
- Instead, it logs an info message and runs a cleanup-only pipeline: `IngestEngine([ChangeDetectionStep, OrphanCleanupStep]).run([], collection_name)`.
- The result is constructed from the pipeline outcome.
- The exception handler remains unchanged.
**Test:** T4

### T3: Add unit tests for IngestSpacePlugin empty corpus cleanup
**File:** `tests/plugins/test_ingest_space.py`
**Depends on:** T1
**Acceptance criteria:**
- `test_empty_corpus_cleanup_deletes_stale_chunks`: pre-populate store, mock empty fetch, assert chunks deleted and result is success.
- `test_fetch_failure_preserves_collection`: mock fetch to raise, assert chunks preserved and result is failure.
**Test:** Self (pytest)

### T4: Add unit tests for IngestWebsitePlugin empty corpus cleanup
**File:** `tests/plugins/test_ingest_website.py`
**Depends on:** T2
**Acceptance criteria:**
- `test_empty_corpus_cleanup_deletes_stale_chunks`: pre-populate store, mock empty crawl, assert chunks deleted and result is success.
- `test_empty_pages_cleanup`: mock crawl returning pages with no extractable text, assert cleanup runs and result is success.
**Test:** Self (pytest)

### T5: Run full test suite and verify green
**Depends on:** T1, T2, T3, T4
**Acceptance criteria:**
- `poetry run pytest` passes with zero failures.
- All existing tests remain green.
- New tests pass.
**Test:** Full suite execution

## Dependency Graph

```
T1 ──> T3 ──┐
             ├──> T5
T2 ──> T4 ──┘
```

T1 and T2 are independent and can be executed in parallel.
T3 depends on T1; T4 depends on T2.
T5 depends on all prior tasks.
