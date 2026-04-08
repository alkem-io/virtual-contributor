# Tasks: Handle Empty Corpus Re-ingestion

**Story:** #35
**Date:** 2026-04-08

---

## Task 1: Modify IngestSpacePlugin to run cleanup on empty documents

**File:** `plugins/ingest_space/plugin.py`
**Dependencies:** None
**Acceptance Criteria:**
- The `if not documents:` block no longer returns early with a bare success.
- Instead, it constructs an `IngestEngine` with `[ChangeDetectionStep, OrphanCleanupStep]` and runs it with `[]` documents and the correct `collection_name`.
- The result of the cleanup pipeline is reflected in the return value (success/failure + error details).
- An info-level log message is emitted indicating cleanup-only mode.
**Proves done by:** Task 4 tests

## Task 2: Modify IngestWebsitePlugin to run cleanup on empty documents

**File:** `plugins/ingest_website/plugin.py`
**Dependencies:** None
**Acceptance Criteria:**
- The `if not documents:` block no longer returns early with a bare success.
- Instead, it constructs an `IngestEngine` with `[ChangeDetectionStep, OrphanCleanupStep]` and runs it with `[]` documents and the correct `collection_name`.
- The result of the cleanup pipeline is reflected in the return value (success/failure + error details).
- An info-level log message is emitted indicating cleanup-only mode.
**Proves done by:** Task 5 tests

## Task 3: Add test for IngestSpacePlugin empty-corpus cleanup

**File:** `tests/plugins/test_ingest_space.py`
**Dependencies:** Task 1
**Acceptance Criteria:**
- `test_empty_documents_runs_cleanup_pipeline`: Mocks `read_space_tree` to return `[]`, verifies the plugin returns success and the cleanup pipeline ran.
- `test_empty_documents_deletes_preexisting_chunks`: Pre-populates the mock store with chunks, mocks `read_space_tree` to return `[]`, verifies chunks are deleted.
- `test_fetch_failure_does_not_cleanup`: Verifies that when `read_space_tree` raises an exception, the error path is taken and no cleanup is attempted.
**Proves done by:** pytest pass

## Task 4: Add test for IngestWebsitePlugin empty-corpus cleanup

**File:** `tests/plugins/test_ingest_website.py`
**Dependencies:** Task 2
**Acceptance Criteria:**
- `test_empty_documents_runs_cleanup_pipeline`: Mocks `crawl` to return `[]`, verifies the plugin returns success and the cleanup pipeline ran (replacing the existing `test_unsupported_content_skip` test which currently just checks for success without verifying cleanup).
- `test_empty_documents_deletes_preexisting_chunks`: Pre-populates the mock store with chunks, mocks `crawl` to return `[]`, verifies chunks are deleted.
**Proves done by:** pytest pass

## Task 5: Verify all exit gates pass

**Dependencies:** Tasks 1-4
**Acceptance Criteria:**
- Full test suite passes (`poetry run pytest`)
- Lint passes (`poetry run ruff check core/ plugins/ tests/`)
- Type check passes (`poetry run pyright core/ plugins/`)
**Proves done by:** Clean CI output
