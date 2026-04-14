# Tasks: Handle Empty Corpus Re-Ingestion

**Input**: Design documents from `specs/012-empty-corpus-reingestion/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md

**Organization**: Tasks grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: User Story 1 -- Empty Space Cleanup (Priority: P1)

**Goal**: When `read_space_tree()` returns an empty list, run a minimal cleanup pipeline to delete all previously stored chunks.

**Independent Test**: Pre-populate a collection, trigger ingest-space with empty space, verify all chunks deleted and result is success.

### Implementation for User Story 1

- [X] T001 [US1] Modify `IngestSpacePlugin.handle()` in plugins/ingest_space/plugin.py: replace the early `return success` on `not documents` with a cleanup pipeline run using `IngestEngine([ChangeDetectionStep, OrphanCleanupStep]).run([], collection_name)`. Add INFO log before cleanup. Return success/failure based on cleanup result.

### Tests for User Story 1

- [X] T002 [US1] Add `test_empty_space_runs_cleanup` in tests/plugins/test_ingest_space.py: mock `read_space_tree` to return `[]`, pre-populate mock store with chunks, assert all chunks deleted after `handle()`.
- [X] T003 [P] [US1] Add `test_empty_space_returns_success` in tests/plugins/test_ingest_space.py: mock `read_space_tree` to return `[]`, assert `result="success"` and `error is None`.
- [X] T004 [P] [US1] Add `test_fetch_failure_no_cleanup` in tests/plugins/test_ingest_space.py: mock `read_space_tree` to raise `RuntimeError`, assert `result="failure"` and store untouched.

**Checkpoint**: IngestSpacePlugin correctly cleans up on empty corpus and preserves failure behavior.

---

## Phase 2: User Story 2 -- Empty Website Cleanup (Priority: P1)

**Goal**: When crawl+extract produces zero documents, run a minimal cleanup pipeline to delete all previously stored chunks.

**Independent Test**: Pre-populate a collection, trigger ingest-website with empty crawl, verify all chunks deleted and result is success.

### Implementation for User Story 2

- [X] T005 [P] [US2] Modify `IngestWebsitePlugin.handle()` in plugins/ingest_website/plugin.py: replace the early `return success` on `not documents` with a cleanup pipeline run using `IngestEngine([ChangeDetectionStep, OrphanCleanupStep]).run([], collection_name)`. Add INFO log before cleanup. Return success/failure based on cleanup result.

### Tests for User Story 2

- [X] T006 [US2] Add `test_empty_crawl_runs_cleanup` in tests/plugins/test_ingest_website.py: mock `crawl` to return `[]`, pre-populate mock store with chunks, assert all chunks deleted after `handle()`.
- [X] T007 [P] [US2] Add `test_empty_extract_runs_cleanup` in tests/plugins/test_ingest_website.py: mock `crawl` to return pages with empty text, pre-populate mock store, assert cleanup runs and chunks deleted.
- [X] T008 [P] [US2] Add `test_empty_crawl_returns_success` in tests/plugins/test_ingest_website.py: assert `result=IngestionResult.SUCCESS` on empty crawl.
- [X] T009 [P] [US2] Add `test_crawl_failure_no_cleanup` in tests/plugins/test_ingest_website.py: mock `crawl` to raise `RuntimeError`, assert `result=IngestionResult.FAILURE` and store untouched.

**Checkpoint**: IngestWebsitePlugin correctly cleans up on empty corpus and preserves failure behavior.

---

## Phase 3: Polish & Cross-Cutting Concerns

- [X] T010 Verify all existing tests pass with `poetry run pytest` -- zero regressions.
- [X] T011 Update `test_unsupported_content_skip` in tests/plugins/test_ingest_website.py to reflect new cleanup behavior (renamed to `test_empty_crawl_returns_success`).

---

## Dependencies & Execution Order

### Phase Dependencies

- **User Story 1 (Phase 1)**: No dependencies -- start immediately
- **User Story 2 (Phase 2)**: No dependencies on Phase 1 -- can run in parallel (different plugin files)
- **Polish (Phase 3)**: Depends on Phases 1 and 2 complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent -- only modifies `plugins/ingest_space/plugin.py` and `tests/plugins/test_ingest_space.py`
- **User Story 2 (P1)**: Independent -- only modifies `plugins/ingest_website/plugin.py` and `tests/plugins/test_ingest_website.py`

### Parallel Opportunities

**Phase 1**: T002, T003, T004 can run in parallel (separate test functions in same file, but T002 depends on T001 for implementation).
**Phase 2**: T005 parallel with T001 (different plugin files). T006-T009 can run in parallel after T005.
**Cross-phase**: T001 and T005 are fully parallel (different files, no shared dependencies).

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete T001: Modify IngestSpacePlugin
2. Complete T002-T004: Add tests for IngestSpacePlugin
3. **STOP and VALIDATE**: Test empty-space cleanup independently
4. Deploy -- stale space content is now cleaned up

### Incremental Delivery

1. T001 + T002-T004 -> IngestSpacePlugin fixed -> Test independently
2. T005 + T006-T009 -> IngestWebsitePlugin fixed -> Test independently
3. T010-T011 -> Full regression verification -> Deploy
