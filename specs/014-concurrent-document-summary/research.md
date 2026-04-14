# Research: Concurrent Document Summarization in DocumentSummaryStep

**Feature Branch**: `story/1823-implement-actual-concurrency-in-document-summary-step`
**Date**: 2026-04-14

## Research Tasks

### R1: Concurrency pattern for async document summarization

**Context**: `DocumentSummaryStep.execute()` accepts a `concurrency` parameter but never uses it --- the method iterates sequentially over qualifying documents with a `for` loop. For spaces with many documents, this results in wall-clock time proportional to `N * per_document_time`, wasting the inherent parallelism available when calling async LLM APIs.

**Findings**:

Python's `asyncio` provides two key primitives for bounded concurrent execution:

1. **`asyncio.Semaphore(N)`**: Limits the number of concurrent coroutines to N. Coroutines acquire the semaphore via `async with sem:` before starting work.
2. **`asyncio.gather(*awaitables)`**: Schedules multiple coroutines concurrently and returns results in the same order as the input awaitables. This ordering guarantee is part of the Python asyncio specification.

The combination of these two primitives provides bounded concurrency with deterministic result ordering.

**Decision**: Use `asyncio.Semaphore(self._concurrency)` + `asyncio.gather()` to execute document summarizations concurrently.
**Rationale**: Both are stdlib primitives with well-defined semantics. No external dependencies. The semaphore bounds concurrency to respect LLM API rate limits. `asyncio.gather` preserves input order, ensuring deterministic output.
**Alternatives considered**: (a) `asyncio.TaskGroup` (Python 3.11+) --- viable but cancels all tasks on first exception, which conflicts with the partial-failure requirement. (b) Manual task creation with `asyncio.create_task` + manual result collection --- more code, same semantics, no benefit. (c) Thread pool via `asyncio.to_thread` --- unnecessary since `_refine_summarize` is already async.

---

### R2: Thread safety of PipelineContext mutations

**Context**: `PipelineContext` is a mutable object with `document_summaries` (dict), `chunks` (list), and `errors` (list). Multiple concurrent coroutines writing to these structures simultaneously could cause race conditions.

**Findings**:

While Python's GIL prevents true data races for simple operations, concurrent async coroutines can still interleave in ways that produce non-deterministic ordering of list appends. This matters because:

1. Summary chunks appended in non-deterministic order would make downstream pipeline behavior unpredictable.
2. Tests would be flaky due to non-deterministic chunk ordering.

The **collect-and-apply** pattern avoids these issues:
1. Each concurrent task returns a `_SummaryResult` dataclass (pure data, no side effects).
2. After `asyncio.gather` completes, a single sequential loop applies results to context in input order.

This guarantees deterministic ordering and avoids any concurrent mutation of shared state.

**Decision**: Use a `_SummaryResult` dataclass to collect task outcomes, then apply them to `PipelineContext` sequentially after all tasks complete.
**Rationale**: Clean separation between concurrent computation and sequential state mutation. Deterministic ordering guaranteed. No locks or synchronization primitives needed.
**Alternatives considered**: (a) `asyncio.Lock` around context mutations --- adds complexity and still results in non-deterministic ordering. (b) Thread-local storage --- inapplicable to async coroutines. (c) Immutable context with merge --- over-engineering for this use case.

---

### R3: Error handling strategy for partial failures

**Context**: Under sequential execution, a failed summarization logs a warning and records an error in `context.errors`, then continues to the next document. The concurrent implementation must preserve this behavior.

**Findings**:

`asyncio.gather` with `return_exceptions=False` (default) propagates the first exception and cancels remaining tasks. This conflicts with the partial-failure requirement.

Two approaches handle this:

1. **Try/except inside each task**: Each `_summarize_one` coroutine catches exceptions internally and returns a `_SummaryResult` with the error field set. `asyncio.gather` always receives successful results.
2. **`asyncio.gather(return_exceptions=True)`**: Exceptions are returned as values. The post-gather loop must type-check each result.

**Decision**: Use try/except inside `_summarize_one`, returning `_SummaryResult(error=...)` on failure.
**Rationale**: The try/except was already present in the sequential version. Moving it into the inner function preserves the same error handling behavior. The post-gather loop has a clean interface: every result is a `_SummaryResult`, not a mixed type. No need for `isinstance` checks.
**Alternatives considered**: `return_exceptions=True` --- viable but produces `list[_SummaryResult | Exception]` requiring type narrowing in the apply loop, which is less clean.

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Concurrency primitive | asyncio.Semaphore + asyncio.gather | Stdlib, bounded, deterministic ordering |
| Context mutation safety | Collect-and-apply pattern via _SummaryResult | No concurrent mutations, deterministic order |
| Error handling | Try/except inside _summarize_one | Preserves sequential behavior, clean result type |
| TaskGroup vs gather | asyncio.gather (not TaskGroup) | TaskGroup cancels all on first error |
