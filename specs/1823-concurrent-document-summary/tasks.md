# Tasks: Implement Actual Concurrency in DocumentSummaryStep

**Story**: alkem-io/alkemio#1823
**Date**: 2026-04-08

---

## Task List

### T1: Add `asyncio` import to `steps.py`

**File**: `core/domain/pipeline/steps.py`
**Depends on**: None
**Description**: Add `import asyncio` to the imports section. Currently the module does not import `asyncio`.
**Acceptance Criteria**: `asyncio` is importable at the top of `steps.py`.
**Test**: Existing tests still pass (no functional change).

### T2: Rewrite `DocumentSummaryStep.execute()` with `asyncio.gather` and `asyncio.Semaphore`

**File**: `core/domain/pipeline/steps.py`
**Depends on**: T1
**Description**: Replace the sequential `for` loop (lines 281-313) with:
1. Create `asyncio.Semaphore(self._concurrency)`.
2. Define inner `async def _summarize_one(doc_id, doc_chunks)` that acquires the semaphore, logs, calls `_refine_summarize`, and returns `(doc_id, summary, summary_chunk)`.
3. Use `asyncio.gather(*tasks, return_exceptions=True)` to run all tasks concurrently.
4. Post-gather loop: for each result, if it is a `BaseException`, append error to `context.errors` and log warning; otherwise, unpack and apply to `context.document_summaries` and `context.chunks`.
**Acceptance Criteria**:
- AC1: Uses `asyncio.gather()` with `asyncio.Semaphore(self._concurrency)`.
- AC2: Summary chunks are appended to `context.chunks` only in the post-gather sequential loop.
- AC3: `context.document_summaries` is updated only in the post-gather sequential loop.
- AC4: Failed documents produce errors without aborting others.
**Test**: All existing `TestDocumentSummaryStep` tests pass. New tests (T3-T6) pass.

### T3: Add test `test_concurrent_execution_multiple_docs`

**File**: `tests/core/domain/test_pipeline_steps.py`
**Depends on**: T2
**Description**: Create a context with 3 documents, each with enough content to exceed the chunk threshold. Run `DocumentSummaryStep`. Assert that all 3 documents get summaries in `context.document_summaries` and all 3 summary chunks are appended.
**Acceptance Criteria**: Test passes and verifies multi-document concurrent summarization produces correct results.
**Test**: Self (the test itself).

### T4: Add test `test_concurrent_error_isolation`

**File**: `tests/core/domain/test_pipeline_steps.py`
**Depends on**: T2
**Description**: Use a mock LLM that raises an exception on a specific document's invocation (e.g., the second document). Verify that the other documents still get their summaries and the failed document's error is recorded in `context.errors`.
**Acceptance Criteria**: Test passes and verifies error isolation between concurrent tasks.
**Test**: Self (the test itself).

### T5: Add test `test_concurrency_1_sequential_behavior`

**File**: `tests/core/domain/test_pipeline_steps.py`
**Depends on**: T2
**Description**: Set `concurrency=1`. Run with multiple documents. Verify all summaries are produced correctly -- identical behavior to what the old sequential loop would produce.
**Acceptance Criteria**: Test passes with `concurrency=1`.
**Test**: Self (the test itself).

### T6: Add test `test_concurrent_semaphore_bounds_parallelism`

**File**: `tests/core/domain/test_pipeline_steps.py`
**Depends on**: T2
**Description**: Create a mock LLM that tracks the maximum number of concurrent invocations (using an asyncio counter incremented before `await` and decremented after). Set `concurrency=2` with 4 documents. Assert that the maximum concurrent invocations never exceeds 2.
**Acceptance Criteria**: Test passes and proves the semaphore correctly limits parallelism.
**Test**: Self (the test itself).

---

## Dependency Order

```
T1 --> T2 --> T3 (independent)
              T4 (independent)
              T5 (independent)
              T6 (independent)
```

T3, T4, T5, T6 are independent of each other and can be implemented in parallel after T2.
