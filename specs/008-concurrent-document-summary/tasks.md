# Tasks: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Date:** 2026-04-08

## Task List

### T1: Add concurrency validation to DocumentSummaryStep.__init__

**Depends on:** None
**File:** `core/domain/pipeline/steps.py`

**Work:**
- Add validation that `concurrency >= 1` in `__init__`, raising `ValueError("concurrency must be >= 1")`.
- This is consistent with the existing `chunk_threshold` validation.

**Acceptance criteria:**
- `DocumentSummaryStep(llm_port=mock, concurrency=0)` raises `ValueError`.
- `DocumentSummaryStep(llm_port=mock, concurrency=1)` succeeds.

**Test:** `test_invalid_concurrency_zero`

---

### T2: Rewrite DocumentSummaryStep.execute() for concurrent execution

**Depends on:** T1
**File:** `core/domain/pipeline/steps.py`

**Work:**
1. Add `import asyncio` at the top of the module.
2. Replace the sequential `for` loop in `execute()` with:
   a. Create `asyncio.Semaphore(self._concurrency)`.
   b. Define inner async function `_summarize_one(doc_id, doc_chunks)` that:
      - Acquires the semaphore.
      - Logs "Summarizing document..." (existing log).
      - Calls `_refine_summarize(...)`.
      - Returns a result tuple: `(doc_id, summary_text, Chunk, None)` on success.
      - Returns a result tuple: `(doc_id, None, None, error_str)` on failure.
      - Logs "Summarized document..." on success, or logs warning on failure.
   c. Dispatch with `asyncio.gather(*[_summarize_one(d, c) for d, c in docs_to_summarize])`.
   d. Post-gather: iterate results, populate `context.document_summaries`, append summary `Chunk` objects to `context.chunks`, append errors to `context.errors`.
3. Sort `docs_to_summarize` by `doc_id` before dispatch for deterministic ordering.

**Acceptance criteria:**
- All existing `TestDocumentSummaryStep` tests pass.
- `_refine_summarize` is called concurrently (not sequentially).
- `context.chunks`, `context.document_summaries`, and `context.errors` are only mutated after gather completes.
- Semaphore limits concurrent calls to `self._concurrency`.

**Tests:** All existing + `test_concurrent_execution`, `test_concurrency_bounded_by_semaphore`

---

### T3: Write new concurrency tests

**Depends on:** T2
**File:** `tests/core/domain/test_pipeline_steps.py`

**Work:**
Add new test methods to `TestDocumentSummaryStep`:

1. `test_concurrent_execution` -- Create 3 documents each with >chunk_threshold chunks. Run DocumentSummaryStep. Assert all 3 get summaries, all 3 have summary chunks with correct metadata, document_summaries dict has all 3 entries.

2. `test_concurrency_bounded_by_semaphore` -- Use a custom LLM mock that tracks peak concurrent invocations using an asyncio counter. Set concurrency=2, provide 4+ documents. Assert peak concurrency never exceeds 2.

3. `test_error_isolation_under_concurrency` -- Use a custom LLM mock that fails for a specific doc_id (based on content). Provide 3 documents, one of which triggers the failure. Assert the other 2 succeed and the failure is in context.errors.

4. `test_concurrency_one_sequential` -- With concurrency=1, verify single-document summarization works identically to default.

5. `test_invalid_concurrency_zero` -- Assert `ValueError` raised.

**Acceptance criteria:**
- All 5 new tests pass.
- All existing tests continue to pass.

**Tests:** The 5 tests listed above.

---

### T4: Verify integration with ingest plugins

**Depends on:** T2
**File:** No code changes needed. Verification only.

**Work:**
- Verify `ingest_website/plugin.py` passes `concurrency=config.summarize_concurrency` (already does, line 103).
- Verify `ingest_space/plugin.py` uses default concurrency=8 (already does via default parameter).
- Run full test suite to confirm no regressions.

**Acceptance criteria:**
- `poetry run pytest` passes with zero failures.
- `poetry run ruff check core/ plugins/ tests/` passes.
- `poetry run pyright core/ plugins/` passes.
