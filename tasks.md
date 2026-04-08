# Tasks: Handle Empty Corpus Re-ingestion

**Story**: alkem-io/virtual-contributor#35
**Plan**: plan.md
**Date**: 2026-04-08

## Task List

### Task 1: Modify IngestSpacePlugin empty-document path

**File**: `plugins/ingest_space/plugin.py`
**Depends on**: None
**Acceptance criteria**:
- The `if not documents:` block at lines 74-81 is replaced with a cleanup-only pipeline invocation.
- The cleanup pipeline consists of `ChangeDetectionStep` + `OrphanCleanupStep` with an empty document list.
- An INFO log message is emitted when entering the cleanup path.
- The plugin returns the appropriate success/failure result based on the cleanup pipeline outcome.
- The fetch-failure path (RuntimeError from missing GraphQL client, or exception from `read_space_tree()`) is unchanged.
**Test**: Task 3 - `test_empty_corpus_cleanup_deletes_existing_chunks`

### Task 2: Modify IngestWebsitePlugin empty-document path

**File**: `plugins/ingest_website/plugin.py`
**Depends on**: None
**Acceptance criteria**:
- The `if not documents:` block at lines 87-91 is replaced with a cleanup-only pipeline invocation.
- The cleanup pipeline consists of `ChangeDetectionStep` + `OrphanCleanupStep` with an empty document list.
- An INFO log message is emitted when entering the cleanup path.
- The plugin returns the appropriate success/failure result based on the cleanup pipeline outcome.
- The crawl-failure path (exception from `crawl()`) is unchanged.
**Test**: Task 4 - `test_empty_corpus_cleanup_deletes_existing_chunks`

### Task 3: Add IngestSpacePlugin empty-corpus tests

**File**: `tests/plugins/test_ingest_space.py`
**Depends on**: Task 1
**Acceptance criteria**:
- New test `test_empty_corpus_cleanup_deletes_existing_chunks`: Seeds MockKnowledgeStorePort with pre-existing chunks under the expected collection name. Mocks `read_space_tree` to return `[]`. Asserts that after `handle()`, the pre-seeded chunks are deleted from the mock store.
- Existing tests pass unchanged.

### Task 4: Add IngestWebsitePlugin empty-corpus tests

**File**: `tests/plugins/test_ingest_website.py`
**Depends on**: Task 2
**Acceptance criteria**:
- New test `test_empty_corpus_cleanup_deletes_existing_chunks`: Seeds MockKnowledgeStorePort with pre-existing chunks under the expected collection name (`example.com-knowledge`). Mocks `crawl` to return `[]`. Asserts that after `handle()`, the pre-seeded chunks are deleted.
- New test `test_crawl_failure_preserves_existing_chunks`: Seeds mock store with chunks. Mocks `crawl` to raise an exception. Asserts chunks are NOT deleted and result is failure.
- Existing tests pass unchanged.

### Task 5: Run full test suite and verify green

**Depends on**: Tasks 1-4
**Acceptance criteria**:
- `poetry run pytest` passes with zero failures.
- `poetry run ruff check core/ plugins/ tests/` passes.
- `poetry run pyright core/ plugins/` passes (or matches pre-existing baseline).

## Dependency Order

```
Task 1 ──┐
          ├── Task 3 ──┐
Task 2 ──┤             ├── Task 5
          └── Task 4 ──┘
```

Tasks 1 and 2 are independent and can be executed in parallel.
Tasks 3 and 4 are independent and can be executed in parallel (after their respective dependency).
Task 5 is the final gate.
