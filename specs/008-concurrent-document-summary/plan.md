# Plan: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Date:** 2026-04-08

## Architecture

The change is localized to a single class (`DocumentSummaryStep`) in the pipeline steps module. No architectural changes are required. The pipeline engine, step protocol, and all other steps remain unchanged.

### Design

```
DocumentSummaryStep.execute(context)
  |
  +-- Build docs_to_summarize list (unchanged)
  |
  +-- Define async _summarize_one(doc_id, doc_chunks) coroutine
  |     |-- Acquires semaphore
  |     |-- Calls _refine_summarize (existing helper, stateless)
  |     |-- Returns (doc_id, summary_text, summary_chunk) on success
  |     |-- Returns (doc_id, None, error_message) on failure
  |
  +-- asyncio.gather(*[_summarize_one(d, c) for d, c in docs_to_summarize])
  |
  +-- Post-gather: iterate results
        |-- Append summaries to context.document_summaries
        |-- Append summary chunks to context.chunks
        |-- Append errors to context.errors
```

The semaphore bounds in-flight LLM calls to `self._concurrency` (default 8).

## Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` | Rewrite `DocumentSummaryStep.execute()` to use `asyncio.Semaphore` + `asyncio.gather()`. Add `import asyncio`. Add concurrency >= 1 validation. |
| `tests/core/domain/test_pipeline_steps.py` | Add new tests for concurrent execution, semaphore bounding, error isolation, deterministic ordering. |

## Data Model Deltas

None. `PipelineContext`, `Chunk`, `DocumentMetadata` are unchanged.

## Interface Contracts

No changes to any interface. `DocumentSummaryStep.__init__` signature is unchanged (concurrency parameter already exists). `PipelineStep` protocol contract (`async execute(context) -> None`) is preserved.

## Test Strategy

### Existing tests (must continue passing)
- `TestDocumentSummaryStep.test_threshold_over_3_chunks`
- `TestDocumentSummaryStep.test_no_summary_for_3_or_fewer_chunks`
- `TestDocumentSummaryStep.test_summary_metadata`
- `TestDocumentSummaryStep.test_populates_document_summaries`
- `TestDocumentSummaryStep.test_per_document_error_handling`
- `TestDocumentSummaryStep.test_step_name`

### New tests
1. **test_concurrent_execution** -- Multiple documents summarized; verify all results present with correct summaries and metadata.
2. **test_concurrency_bounded_by_semaphore** -- Use a tracking LLM mock that records concurrent invocation count; verify max concurrent calls does not exceed the concurrency parameter.
3. **test_error_isolation_under_concurrency** -- One document's summarization fails; verify other documents complete successfully and error is recorded.
4. **test_concurrency_one_sequential** -- With concurrency=1, behavior is equivalent to sequential (results identical to existing tests).
5. **test_invalid_concurrency_zero** -- Verify ValueError raised for concurrency=0.

## Rollout Notes

- Zero-config change. The `SUMMARIZE_CONCURRENCY` env var already exists and defaults to 8.
- The ingest-website plugin already passes `config.summarize_concurrency` to `DocumentSummaryStep`.
- The ingest-space plugin does not pass `concurrency` explicitly, so it uses the default of 8 (unchanged behavior since the parameter was never effective before).
- Backward compatible: setting `SUMMARIZE_CONCURRENCY=1` gives exactly the old sequential behavior.
