# Tasks: Handle Empty Corpus Re-Ingestion

**Story:** #35
**Date:** 2026-04-14

## Task List

### T1: Modify IngestSpacePlugin to run cleanup pipeline on empty documents

**File:** `plugins/ingest_space/plugin.py`
**Depends on:** None
**Description:** Replace the early `return success` block (lines 74-81) with logic that runs a minimal cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) when `read_space_tree()` returns an empty list. Add an info-level log message. The failure path (exception from `read_space_tree()`) remains unchanged since it's caught by the outer try/except.
**Acceptance criteria:**
- When `read_space_tree()` returns `[]`, a cleanup pipeline with `ChangeDetectionStep` + `OrphanCleanupStep` runs against the collection.
- The plugin returns `result="success"` after cleanup completes without errors, or `result="failure"` if cleanup had errors.
- An info-level log message is emitted before running cleanup.
- When `read_space_tree()` raises an exception, the existing error handling (lines 109-118) catches it and returns failure without any cleanup.
**Tests:** T3

### T2: Modify IngestWebsitePlugin to run cleanup pipeline on empty documents

**File:** `plugins/ingest_website/plugin.py`
**Depends on:** None
**Description:** Replace the early `return success` block (lines 87-91) with logic that runs a minimal cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) when the crawl+extract produces zero documents. Add an info-level log message. The failure path (exception from `crawl()`) remains unchanged since it's caught by the outer try/except.
**Acceptance criteria:**
- When crawl+extract produces zero documents, a cleanup pipeline with `ChangeDetectionStep` + `OrphanCleanupStep` runs against the collection.
- The plugin returns `result=IngestionResult.SUCCESS` after cleanup completes without errors, or `result=IngestionResult.FAILURE` if cleanup had errors.
- An info-level log message is emitted before running cleanup.
- When `crawl()` raises an exception, the existing error handling (lines 121-126) catches it and returns failure without any cleanup.
**Tests:** T4

### T3: Add unit tests for IngestSpacePlugin empty-corpus cleanup

**File:** `tests/plugins/test_ingest_space.py`
**Depends on:** T1
**Description:** Add test cases to `TestIngestSpacePlugin`:
1. `test_empty_space_runs_cleanup` -- Mock `read_space_tree` to return `[]`. Pre-populate mock store with chunks. Assert chunks are deleted after `handle()`.
2. `test_empty_space_returns_success` -- Mock `read_space_tree` to return `[]`. Assert `result="success"`.
3. `test_fetch_failure_no_cleanup` -- Mock `read_space_tree` to raise. Assert `result="failure"` and store untouched.
**Acceptance criteria:**
- All three test cases pass.
- Tests use existing mock infrastructure from `conftest.py`.
- Tests verify both the return value and the side effects on the knowledge store.

### T4: Add unit tests for IngestWebsitePlugin empty-corpus cleanup

**File:** `tests/plugins/test_ingest_website.py`
**Depends on:** T2
**Description:** Add/modify test cases in `TestIngestWebsitePlugin`:
1. `test_empty_crawl_runs_cleanup` -- Mock `crawl` to return `[]`. Pre-populate mock store with chunks. Assert chunks are deleted after `handle()`.
2. `test_empty_extract_runs_cleanup` -- Mock `crawl` to return pages with empty text. Pre-populate mock store. Assert cleanup runs.
3. `test_crawl_failure_no_cleanup` -- Mock `crawl` to raise. Assert `result=IngestionResult.FAILURE` and store untouched.
4. Update `test_unsupported_content_skip` to verify cleanup behavior instead of the old early-return behavior.
**Acceptance criteria:**
- All test cases pass.
- Tests use existing mock infrastructure.
- Tests verify both the return value and the side effects on the knowledge store.

### T5: Verify all existing tests pass

**Depends on:** T1, T2, T3, T4
**Description:** Run the full test suite to confirm no regressions.
**Acceptance criteria:**
- `poetry run pytest` passes with zero failures.
- All pre-existing tests still pass.
