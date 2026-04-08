# Tasks: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Plan:** `plan.md`
**Date:** 2026-04-08

---

## Task List (dependency-ordered)

### T1: Add concurrency validation to DocumentSummaryStep.__init__

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**Description:** Add validation that `concurrency >= 1` in the `__init__` method, raising `ValueError` for invalid values. This matches the existing `chunk_threshold` validation pattern.
**Acceptance criteria:**
- `DocumentSummaryStep(llm_port=llm, concurrency=0)` raises `ValueError`
- `DocumentSummaryStep(llm_port=llm, concurrency=-1)` raises `ValueError`
- `DocumentSummaryStep(llm_port=llm, concurrency=1)` succeeds
**Test:** `test_concurrency_validation`

### T2: Rewrite DocumentSummaryStep.execute() with asyncio.gather + Semaphore

**File:** `core/domain/pipeline/steps.py`
**Depends on:** T1
**Description:** Replace the sequential `for` loop (lines 281-313) with:
1. Create `asyncio.Semaphore(self._concurrency)`.
2. Define an inner async function `_summarize_one(index, doc_id, doc_chunks)` that acquires the semaphore, calls `_refine_summarize`, and returns a result dataclass (or error string on exception).
3. Use `asyncio.gather(*tasks)` to run all document summarizations concurrently.
4. After gather completes, iterate results in original order, applying successes to `context.document_summaries` and `context.chunks`, and failures to `context.errors`.
**Acceptance criteria:**
- `asyncio.Semaphore` is used with `self._concurrency` as the bound.
- `asyncio.gather` is called on all document coroutines.
- Results are applied to context in original `docs_to_summarize` order.
- Per-document try/except catches and returns errors without aborting gather.
- `import asyncio` is added to the module.
**Test:** All existing `TestDocumentSummaryStep` tests pass + new concurrency tests.

### T3: Wire concurrency parameter in ingest_space plugin

**File:** `plugins/ingest_space/plugin.py`
**Depends on:** T2
**Description:** Add `concurrency=config.summarize_concurrency` to the `DocumentSummaryStep` constructor call in `ingest_space/plugin.py`, matching the existing wiring in `ingest_website/plugin.py`. Requires reading config via `BaseConfig()`.
**Acceptance criteria:**
- `DocumentSummaryStep` in ingest_space is constructed with explicit `concurrency` from config.
**Test:** Code review (no dedicated test — ingest_space plugin tests are integration-level).

### T4: Write new concurrency unit tests

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T2
**Description:** Add the following test cases to `TestDocumentSummaryStep`:

1. `test_concurrent_summarization_multiple_docs` — Create 4+ documents each with enough chunks to trigger summarization. Use a mock LLM that records call timestamps. Verify all documents get summaries.
2. `test_concurrency_one_is_sequential` — With `concurrency=1`, verify results are identical to sequential execution (same summaries, same chunk order).
3. `test_concurrent_error_isolation` — Use a mock LLM that fails for one specific document but succeeds for others. Verify the failing document's error is in `context.errors` and the succeeding documents have their summaries.
4. `test_results_applied_in_order` — With multiple documents, verify summary chunks in `context.chunks` appear in the original iteration order of `docs_to_summarize`.
5. `test_concurrency_validation` — Verify `ValueError` is raised for `concurrency=0` and `concurrency=-1`.

**Acceptance criteria:**
- All 5 new tests pass.
- All 6 existing `TestDocumentSummaryStep` tests pass unchanged.
**Test:** Self-verifying.

### T5: Run full test suite and verify green

**Depends on:** T1, T2, T3, T4
**Description:** Execute `poetry run pytest` to confirm all tests pass. Run `poetry run ruff check` and `poetry run pyright` to confirm lint and type checks pass.
**Acceptance criteria:**
- All tests pass.
- No lint errors.
- No type errors.
