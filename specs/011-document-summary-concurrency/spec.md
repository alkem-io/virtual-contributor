# Spec: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Epic:** alkem-io/alkemio#1820
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

---

## 1. User Value

Ingest pipelines processing 15+ documents (typical for a 20-page website crawl) currently spend 300-450 seconds in sequential document summarization. This is the single highest-impact performance bottleneck in the ingest pipeline. Enabling true concurrency (semaphore-bounded `asyncio.gather`) will reduce summarization wall time by 5-10x (to 30-60 seconds), directly reducing the risk of hitting RabbitMQ's `consumer_timeout` and eliminating the need for the current 2-hour timeout workaround.

## 2. Scope

- **In scope:**
  - Wire the existing `concurrency: int` parameter in `DocumentSummaryStep` to an `asyncio.Semaphore`-bounded `asyncio.gather` call, replacing the sequential `for` loop.
  - Ensure thread-safe mutation of `context.chunks` (list append) and `context.document_summaries` (dict update) during concurrent execution.
  - Ensure per-document error handling is preserved (individual document failures do not crash the entire gather).
  - Maintain backward compatibility: `concurrency=1` must behave identically to current sequential behavior.
  - Unit tests proving concurrency, correctness, and error isolation.

- **Out of scope:**
  - Changing the `_refine_summarize` helper itself.
  - Concurrency in other pipeline steps (EmbedStep, StoreStep, etc.).
  - Changing the config schema or adding new config fields (the `summarize_concurrency` field already exists in `core/config.py`).
  - Modifications to the pipeline engine (`IngestEngine`).

## 3. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|--------------|
| AC-1 | `DocumentSummaryStep.execute()` uses `asyncio.gather` with an `asyncio.Semaphore(self._concurrency)` to process documents concurrently. | Code review + unit test |
| AC-2 | `context.chunks` and `context.document_summaries` are updated safely without race conditions. Results are collected from gather and applied after all tasks complete. | Code review + unit test |
| AC-3 | Per-document errors are caught individually and appended to `context.errors` without aborting other concurrent documents. | Unit test with a failing LLM mock |
| AC-4 | `concurrency=1` produces identical results to the former sequential loop. | Unit test |
| AC-5 | All existing `TestDocumentSummaryStep` tests continue to pass unchanged. | Test suite |
| AC-6 | New tests demonstrate actual concurrency (multiple documents processed in parallel within the semaphore bound). | Unit test with timing or call-order assertions |

## 4. Constraints

- Python 3.12, asyncio only (no threading, no multiprocessing).
- Must not break the `PipelineStep` protocol interface (`name` property + `async execute(context)`).
- Must not modify the `_refine_summarize` shared helper function.
- Must collect results in a local list and batch-apply them to `context` after `gather` completes, avoiding concurrent mutation of shared state.
