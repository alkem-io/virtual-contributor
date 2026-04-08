# Spec: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

Ingest pipeline users (Alkemio platform operators and end users triggering website/space ingestion) experience 300-450 second waits for document summarization of typical 20-page websites. This change delivers a 5-10x speedup by executing document summaries concurrently, reducing summarization to 30-60 seconds and eliminating the risk of RabbitMQ consumer_timeout disconnections.

## Scope

1. Modify `DocumentSummaryStep.execute()` to use `asyncio.Semaphore`-bounded `asyncio.gather()` for concurrent document summarization.
2. Ensure thread-safe mutation of shared `PipelineContext` state (`context.chunks`, `context.document_summaries`, `context.errors`) during concurrent execution.
3. Wire the existing `self._concurrency` parameter (already accepted in `__init__`, already configurable via `SUMMARIZE_CONCURRENCY` in `core/config.py`) through to the semaphore.
4. Add comprehensive tests proving concurrency, correctness, and error isolation.

## Out of Scope

- Changes to `BodyOfKnowledgeSummaryStep` (sequential by design -- single BoK summary).
- Changes to the `_refine_summarize` helper function itself.
- Changes to the `SUMMARIZE_CONCURRENCY` config field (already exists at `core/config.py:216`).
- Changes to the pipeline engine or other pipeline steps.
- Performance benchmarking or load testing.

## Acceptance Criteria

1. `DocumentSummaryStep.execute()` runs document summarizations concurrently, bounded by `self._concurrency`.
2. An `asyncio.Semaphore(self._concurrency)` gates the number of in-flight summarization coroutines.
3. `context.chunks` list is not mutated during `asyncio.gather()` -- summary chunks are collected first, then bulk-appended after gather completes.
4. `context.document_summaries` dict is populated safely -- results collected then merged after gather.
5. `context.errors` is populated safely -- errors collected then merged after gather.
6. Per-document error isolation is preserved: one failing summarization does not abort others.
7. Behavior with `concurrency=1` is identical to the previous sequential implementation.
8. All existing `TestDocumentSummaryStep` tests continue to pass.
9. New tests validate: (a) concurrent execution ordering, (b) semaphore bounding, (c) error isolation under concurrency, (d) thread-safe result collection.

## Constraints

- Python 3.12, asyncio only (no threading, no multiprocessing).
- Must not break the `PipelineStep` protocol contract (`async execute(context) -> None`).
- Must not change the public interface of `DocumentSummaryStep.__init__`.
- The `_refine_summarize` helper is a pure async function with no shared state -- safe to call concurrently.
