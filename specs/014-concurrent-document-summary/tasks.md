# Tasks: Concurrent Document Summarization in DocumentSummaryStep

**Input**: Design documents from `specs/014-concurrent-document-summary/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Single user story, tasks grouped by phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

---

## Phase 1: Core Concurrency Refactor

**Purpose**: Replace the sequential for-loop in DocumentSummaryStep with asyncio.gather + Semaphore.

- [X] T001 [US1] Add `_SummaryResult` dataclass with fields `doc_id: str`, `summary: str | None`, `chunk: Chunk | None`, `error: str | None` to core/domain/pipeline/steps.py (module-private, above DocumentSummaryStep class)
- [X] T002 [US1] Add `import asyncio` and `from dataclasses import dataclass` to core/domain/pipeline/steps.py
- [X] T003 [US1] Update DocumentSummaryStep class docstring to describe concurrent execution via asyncio.Semaphore and the collect-and-apply pattern
- [X] T004 [US1] Add early return in `execute()` when `docs_to_summarize` is empty, before creating the semaphore
- [X] T005 [US1] Create `asyncio.Semaphore(self._concurrency)` in `execute()` after the early return guard
- [X] T006 [US1] Extract the per-document summarization logic from the for-loop into an inner async function `_summarize_one(doc_id, doc_chunks) -> _SummaryResult` that acquires the semaphore via `async with sem`
- [X] T007 [US1] Replace the sequential for-loop with `asyncio.gather(*[_summarize_one(d, c) for d, c in docs_to_summarize])` to fan out concurrent summarizations
- [X] T008 [US1] Add a post-gather loop that iterates over `results` in input order, applying errors to `context.errors` and successful summaries/chunks to `context.document_summaries` and `context.chunks`

**Checkpoint**: DocumentSummaryStep executes concurrently with deterministic result ordering and thread-safe context mutation.

---

## Phase 2: Tests

**Purpose**: Verify concurrency behavior, deterministic ordering, partial failure handling, and context integrity.

- [X] T009 [P] [US1] Add `_make_multi_doc_context(n_docs, chunks_per_doc, collection)` helper function to tests/core/domain/test_pipeline_steps.py for building multi-document PipelineContext fixtures
- [X] T010 [P] [US1] Add `_DelayedLLMPort(delay, response)` mock class with asyncio.sleep-based delay in tests/core/domain/test_pipeline_steps.py
- [X] T011 [P] [US1] Add `_SelectiveFailLLMPort(fail_marker, response)` mock class that raises RuntimeError when prompt content contains the fail_marker in tests/core/domain/test_pipeline_steps.py
- [X] T012 [US1] Add `test_concurrent_execution_faster_than_sequential` test: 3 docs, 100ms delay, concurrency=3, assert elapsed < 80% of sequential estimate
- [X] T013 [US1] Add `test_deterministic_ordering_of_summary_chunks` test: 4 docs with varying delays (0.08, 0.02, 0.06, 0.01s), assert summary chunks in input order
- [X] T014 [US1] Add `test_partial_failure_does_not_block_other_documents` test: 3 docs, doc-1 fails, assert doc-0 and doc-2 have summaries, doc-1 has error
- [X] T015 [US1] Add `test_concurrency_one_produces_correct_results` test: concurrency=1, assert all docs summarized correctly in order
- [X] T016 [US1] Add `test_multiple_documents_all_summarized` test: 5 docs, concurrency=8, chunk_threshold=4, assert all summaries produced
- [X] T017 [US1] Add `test_no_context_corruption_under_concurrency` test: 10 docs, concurrency=5, assert chunk count, summary count, no errors, unique doc IDs

**Checkpoint**: All 6 concurrency tests pass, covering timing, ordering, failure isolation, and state integrity.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Core Refactor)**: No dependencies --- start immediately
- **Phase 2 (Tests)**: Depends on Phase 1 (tests exercise the refactored code)

### Parallel Opportunities

**Phase 1**: T001-T003 are independent setup tasks (can be parallel). T004-T008 are sequential (each builds on the previous, same function).
**Phase 2**: T009-T011 (helper classes) are parallel with each other. T012-T017 (test methods) are independent but depend on T009-T011.

---

## Implementation Strategy

### Single MVP Delivery

1. Complete Phase 1: Refactor DocumentSummaryStep for concurrency
2. Complete Phase 2: Add all concurrency tests
3. **VALIDATE**: Run `poetry run pytest tests/core/domain/test_pipeline_steps.py` --- all tests pass
4. **VALIDATE**: Run `poetry run ruff check core/ tests/` --- no lint violations
5. Deploy --- DocumentSummaryStep now runs concurrent summarizations bounded by semaphore
