# Tasks: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Plan:** plan.md
**Date:** 2026-04-08

---

## Task List

### T1: Rewrite DocumentSummaryStep.execute() with asyncio concurrency

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**Acceptance criteria:**
- The sequential `for doc_id, doc_chunks in docs_to_summarize:` loop is replaced with `asyncio.gather()`
- An `asyncio.Semaphore(self._concurrency)` bounds parallel execution
- Per-document results (summary text + summary Chunk) are collected in a list
- After gather, results are batch-applied to `context.document_summaries` and `context.chunks`
- Errors are collected per-document and batch-appended to `context.errors` after gather
- `import asyncio` is added at the top of the file
- Logging is preserved (info log before and after each doc summarization)
**Tests:** All existing `TestDocumentSummaryStep` tests pass. New tests in T3.

### T2: Wire concurrency parameter in ingest-space plugin

**File:** `plugins/ingest_space/plugin.py`
**Depends on:** None (can be done in parallel with T1)
**Acceptance criteria:**
- `DocumentSummaryStep` instantiation passes `concurrency=` from config, matching ingest-website plugin pattern
- Config is read from `BaseConfig().summarize_concurrency`
**Tests:** Existing plugin tests pass.

### T3: Add concurrency-specific unit tests

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- `test_concurrent_multiple_documents`: Creates 3+ documents that each produce enough chunks to trigger summarization. Verifies all documents get summaries in `context.document_summaries` and corresponding summary chunks in `context.chunks`.
- `test_concurrent_error_isolation`: One document's LLM call raises an exception; other documents succeed. Verifies errors list contains the failure, and successful documents have their summaries.
- `test_concurrency_semaphore_bounds`: Uses a tracking LLM to record peak concurrency. Verifies peak does not exceed the configured `concurrency` parameter.
- `test_concurrent_change_detection_respected`: When `change_detection_ran=True`, only documents in `changed_document_ids` are summarized (existing behavior preserved under concurrency).
**Tests:** Self-referential -- these ARE the tests.

### T4: Verify all exit gates pass

**Depends on:** T1, T2, T3
**Acceptance criteria:**
- `poetry run pytest` passes with zero failures
- `poetry run ruff check core/ plugins/ tests/` passes clean
- `poetry run pyright core/ plugins/` passes clean
**Tests:** Gate verification.
