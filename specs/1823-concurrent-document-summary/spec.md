# Spec: Implement Actual Concurrency in DocumentSummaryStep

**Story**: alkem-io/alkemio#1823
**Status**: Draft
**Author**: SDD Agent
**Date**: 2026-04-08

---

## User Value

Ingest pipelines processing 15+ documents currently take 300-450 seconds for summarization because `DocumentSummaryStep.execute()` processes documents sequentially despite accepting a `concurrency` parameter. Implementing true concurrent summarization with `asyncio.Semaphore`-bounded `asyncio.gather()` will reduce this to 30-60 seconds (5-10x improvement), directly mitigating RabbitMQ `consumer_timeout` risks and eliminating the need for the 2-hour timeout workaround.

## Scope

### In Scope

1. Replace the sequential `for` loop in `DocumentSummaryStep.execute()` (steps.py lines 281-313) with `asyncio.Semaphore`-bounded `asyncio.gather()` for concurrent document summarization.
2. Ensure thread-safe mutation of shared state (`context.chunks`, `context.document_summaries`, `context.errors`) during concurrent execution.
3. Wire the existing `self._concurrency` parameter (already populated from `config.summarize_concurrency`) into the semaphore.
4. Add tests verifying concurrent execution, correctness of results, thread safety, and error isolation.

### Out of Scope

- Changes to the `_refine_summarize` helper function itself.
- Changes to `BodyOfKnowledgeSummaryStep` (depends on `document_summaries` being populated first; remains sequential by nature).
- Changes to `PipelineContext` dataclass fields.
- Changes to config defaults or environment variable naming.
- Performance benchmarking or telemetry instrumentation.
- Changes to plugin-level code in `ingest_website` or `ingest_space` (they already pass `concurrency` correctly).

## Acceptance Criteria

1. **AC1**: `DocumentSummaryStep.execute()` uses `asyncio.gather()` with an `asyncio.Semaphore(self._concurrency)` to process documents concurrently.
2. **AC2**: Mutations to `context.chunks` (appending summary chunks) are collected from concurrent tasks and applied after `gather()` completes, avoiding race conditions on the shared list.
3. **AC3**: Mutations to `context.document_summaries` and `context.errors` are similarly protected from concurrent mutation.
4. **AC4**: When any single document's summarization fails, it is logged and recorded in `context.errors` without aborting other concurrent summarizations.
5. **AC5**: The existing `concurrency=1` behavior produces identical results to the previous sequential implementation (regression safety).
6. **AC6**: All existing `TestDocumentSummaryStep` tests continue to pass.
7. **AC7**: New tests verify: (a) concurrent execution occurs, (b) results are correct with multiple documents, (c) error in one document does not affect others, (d) concurrency=1 produces correct sequential behavior.

## Constraints

- Python 3.12 / asyncio only. No threading primitives (the event loop is single-threaded; `asyncio.Lock` is unnecessary for dict/list mutation within `gather` callbacks as long as mutations happen outside the `await` boundary).
- The `_refine_summarize` function is `async` and the `llm.invoke` within it yields control. Multiple coroutines calling it concurrently will interleave at `await` points. Shared mutable state must not be modified during awaits within individual task coroutines.
- Must preserve the exact order-independence semantics: summary chunks can be appended in any order since downstream steps (EmbedStep, StoreStep) do not depend on chunk ordering.
- Must not change the public interface of `DocumentSummaryStep.__init__()`.
