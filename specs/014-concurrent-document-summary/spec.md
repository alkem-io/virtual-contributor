# Feature Specification: Concurrent Document Summarization in DocumentSummaryStep

**Feature Branch**: `story/1823-implement-actual-concurrency-in-document-summary-step`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing *(mandatory)*

### User Story 1 --- Concurrent Document Summarization (Priority: P1)

As a platform operator running large ingestion workloads, I want the DocumentSummaryStep to summarize multiple documents in parallel so that ingest pipelines complete significantly faster when many documents qualify for summarization.

**Why this priority**: The DocumentSummaryStep already accepts a `concurrency` parameter but executes all summarizations sequentially in a `for` loop. For spaces with many documents (10+), the wall-clock time is `N * per_document_time`. Enabling true concurrency via `asyncio.gather` with a semaphore yields 5-10x speedup with no additional infrastructure cost.

**Independent Test**: Ingest a space with 10+ documents, each with enough chunks to qualify for summarization. Measure wall-clock time. Compare against sequential execution (concurrency=1). Verify that concurrent execution completes in significantly less time.

**Acceptance Scenarios**:

1. **Given** a pipeline with 3 documents qualifying for summarization and `concurrency=3`, **When** the DocumentSummaryStep executes, **Then** all 3 documents are summarized concurrently and the total time is roughly `1/3` of sequential execution.
2. **Given** a pipeline with 10 documents and `concurrency=5`, **When** the step executes, **Then** at most 5 summarizations run concurrently at any point in time (bounded by semaphore).
3. **Given** concurrent summarization where documents complete in different order than input, **When** results are applied to the PipelineContext, **Then** summary chunks appear in the original input document order (deterministic ordering).
4. **Given** concurrent summarization where one document fails, **When** the step completes, **Then** all other documents still have their summaries and an error is recorded only for the failed document.
5. **Given** `concurrency=1`, **When** the step executes, **Then** behavior is equivalent to sequential execution with correct results.
6. **Given** 10 documents running concurrently with `concurrency=5`, **When** the step completes, **Then** `context.chunks` contains exactly `initial_count + 10` entries, `context.document_summaries` has 10 keys, and all summary document IDs are unique (no context corruption).

---

### Edge Cases

- When zero documents qualify for summarization (all below `chunk_threshold` or no changed documents), the step returns immediately without creating a semaphore or calling `asyncio.gather`.
- When all concurrent summarizations fail, `context.document_summaries` remains empty, `context.errors` contains one entry per failed document, and no summary chunks are appended.
- When `concurrency` exceeds the number of documents, all documents run simultaneously (semaphore does not block any tasks).
- When `concurrency=1`, behavior is strictly sequential --- one document at a time.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The DocumentSummaryStep MUST execute document summarizations concurrently using `asyncio.gather`, bounded by an `asyncio.Semaphore` initialized to the `concurrency` parameter value.
- **FR-002**: All mutations to `PipelineContext` (adding to `document_summaries`, appending to `chunks`, appending to `errors`) MUST happen after `asyncio.gather` completes, using a collect-and-apply pattern to avoid race conditions.
- **FR-003**: Summary chunks MUST be appended to `context.chunks` in the original input document order, regardless of which summarization task completes first.
- **FR-004**: When summarization fails for a document, the error MUST be recorded in `context.errors` and other documents MUST still complete successfully.
- **FR-005**: When no documents qualify for summarization, the step MUST return immediately without performing any async operations.
- **FR-006**: A `_SummaryResult` dataclass MUST be used to collect the outcome (success or error) of each summarization task before applying results to context.

### Key Entities

- **DocumentSummaryStep**: Pipeline step that generates per-document summaries for documents exceeding a chunk threshold. Now uses `asyncio.Semaphore` + `asyncio.gather` for concurrent execution.
- **_SummaryResult**: Internal dataclass capturing the outcome of a single summarization task --- either a summary string and chunk, or an error message.
- **PipelineContext**: Shared mutable state for the ingest pipeline. Mutations are deferred until after all concurrent tasks complete.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Concurrent execution with `concurrency=N` and N qualifying documents completes in less than 80% of sequential wall-clock time for the same workload.
- **SC-002**: Summary chunks in `context.chunks` are always in deterministic input-document order, verified by tests with varying completion delays.
- **SC-003**: Partial failures do not block or corrupt results for successful documents --- failed and successful documents are handled independently.
- **SC-004**: No context corruption under concurrency --- `context.chunks` count, `context.document_summaries` count, and summary document ID uniqueness are all verified.

## Assumptions

- The `_refine_summarize` function is safe to call concurrently from multiple coroutines because each call operates on independent inputs and uses its own `llm.invoke` call chain.
- `asyncio.gather` preserves result order matching the input order of awaitables, which is guaranteed by the Python asyncio specification.
- The existing `LLMPort.invoke` implementation is coroutine-safe --- multiple concurrent `invoke` calls to the same adapter do not interfere with each other.
- The `concurrency` parameter default of 8 is appropriate for typical LLM API rate limits and provides good parallelism without excessive resource contention.

## Clarifications

- **Q**: Does the concurrency change affect the BodyOfKnowledgeSummaryStep?
  **A**: No. Only `DocumentSummaryStep` is modified. `BodyOfKnowledgeSummaryStep` processes a single aggregated summary and does not benefit from concurrency.
- **Q**: Is the `_SummaryResult` dataclass exposed as public API?
  **A**: No. It is a module-private helper class (prefixed with underscore) used only within `DocumentSummaryStep.execute()`.
