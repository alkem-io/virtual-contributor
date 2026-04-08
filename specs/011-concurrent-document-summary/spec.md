# Spec: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Parent:** alkem-io/alkemio#1820
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

---

## User Value

Website and space ingestion currently takes 300-450 seconds for 15+ document summarizations because `DocumentSummaryStep.execute()` processes documents sequentially. Implementing semaphore-bounded `asyncio.gather` concurrency will reduce this to 30-60 seconds (5-10x improvement), directly reducing the risk of hitting RabbitMQ `consumer_timeout` and eliminating the need for the 2-hour timeout workaround.

## Scope

1. Replace the sequential `for` loop in `DocumentSummaryStep.execute()` with `asyncio.Semaphore`-bounded `asyncio.gather()`.
2. Ensure thread-safe updates to `context.chunks` (list append) and `context.document_summaries` (dict update) during concurrent execution.
3. Ensure thread-safe collection of per-document errors during concurrent execution.
4. Wire the existing `self._concurrency` parameter (already accepted in `__init__`, already configured via `SUMMARIZE_CONCURRENCY` env var) through to the semaphore.
5. Write unit tests proving concurrent execution, correctness of results, and proper error isolation.

## Out of Scope

- Changing the `_refine_summarize` helper itself (it is correct as-is).
- Adding concurrency to `BodyOfKnowledgeSummaryStep` (single sequential call by design).
- Modifying RabbitMQ timeout configuration.
- Changing the `PipelineContext` dataclass structure.
- Concurrency in other pipeline steps (EmbedStep, StoreStep).

## Acceptance Criteria

1. **AC-1:** `DocumentSummaryStep.execute()` uses `asyncio.gather()` with `asyncio.Semaphore(self._concurrency)` to process documents concurrently.
2. **AC-2:** `context.chunks`, `context.document_summaries`, and `context.errors` are updated safely -- no race conditions, no lost data.
3. **AC-3:** The `concurrency` parameter (default 8, from `SUMMARIZE_CONCURRENCY` config) controls the semaphore limit.
4. **AC-4:** Per-document error handling is preserved -- a failure in one document does not abort other documents.
5. **AC-5:** All existing `TestDocumentSummaryStep` tests continue to pass without modification.
6. **AC-6:** New tests verify concurrent execution (multiple documents processed), error isolation, and correct semaphore bounding.
7. **AC-7:** Lint, typecheck, and full test suite pass clean.

## Constraints

- Python 3.12, asyncio only (no threading, no multiprocessing).
- Must not change the `PipelineStep` protocol or `PipelineContext` dataclass.
- Must preserve the existing public interface of `DocumentSummaryStep.__init__`.
- Collect results from `asyncio.gather` and batch-apply to context after gather completes (avoids interleaved mutation).
