# Plan: Implement Actual Concurrency in DocumentSummaryStep

**Story**: alkem-io/alkemio#1823
**Date**: 2026-04-08

---

## Architecture

### Affected Module

`core/domain/pipeline/steps.py` -- `DocumentSummaryStep.execute()` method (lines 265-313).

No new modules, classes, or files are introduced. The change is a surgical replacement of the sequential loop with a concurrent gather pattern.

### Design

The current sequential loop:

```
for doc_id, doc_chunks in docs_to_summarize:
    summary = await _refine_summarize(...)
    context.document_summaries[doc_id] = summary
    context.chunks.append(Chunk(...))
```

Is replaced with:

```
sem = asyncio.Semaphore(self._concurrency)

async def _summarize_one(doc_id, doc_chunks):
    async with sem:
        summary = await _refine_summarize(...)
        return (doc_id, summary, Chunk(...))

results = await asyncio.gather(
    *[_summarize_one(d, c) for d, c in docs_to_summarize],
    return_exceptions=True
)

# Apply results to context (single-threaded, no concurrency concerns)
for i, result in enumerate(results):
    if isinstance(result, BaseException):
        doc_id = docs_to_summarize[i][0]
        context.errors.append(f"DocumentSummaryStep: summarization failed for {doc_id}: {result}")
    else:
        doc_id, summary, chunk = result
        context.document_summaries[doc_id] = summary
        context.chunks.append(chunk)
```

### Key Design Decisions

1. **`return_exceptions=True` with post-gather filtering** -- After further analysis, this is actually cleaner than per-task try/except because it lets us build the result tuple only on success and handle all failures uniformly in the post-gather loop. The logging of per-document progress still happens inside `_summarize_one`.

2. **No `asyncio.Lock`** -- All mutations to `context` happen in the post-gather sequential loop, not inside concurrent tasks. The concurrent tasks only read from `context` (to get chunk content) and return pure values.

3. **Semaphore bounds concurrency** -- The existing `self._concurrency` parameter (default 8) controls the semaphore. This prevents overwhelming the LLM API with too many simultaneous requests.

## Data Model Deltas

None. `PipelineContext` is unchanged.

## Interface Contracts

No public interface changes. `DocumentSummaryStep.__init__()` signature is unchanged. `DocumentSummaryStep.execute()` signature is unchanged. The behavioral contract (populates `context.document_summaries` and appends summary chunks to `context.chunks`) is preserved.

## Test Strategy

### Existing Tests (Regression)

All 6 existing `TestDocumentSummaryStep` tests must continue to pass unchanged:
- `test_threshold_over_3_chunks`
- `test_no_summary_for_3_or_fewer_chunks`
- `test_summary_metadata`
- `test_populates_document_summaries`
- `test_per_document_error_handling`
- `test_step_name`

### New Tests

1. **`test_concurrent_execution_multiple_docs`** -- Create context with 3+ documents each exceeding chunk threshold. Verify all get summaries and summary chunks. Verify `document_summaries` dict has entries for all documents.

2. **`test_concurrent_error_isolation`** -- Use an LLM mock that fails for a specific document ID. Verify other documents still get their summaries. Verify the failed document's error is recorded.

3. **`test_concurrency_1_sequential_behavior`** -- Set `concurrency=1`. Verify correct results identical to what the old sequential code would produce.

4. **`test_concurrent_uses_semaphore`** -- Verify that with concurrency=2 and 4 documents, at most 2 are processed simultaneously (by tracking concurrent invocations in the mock LLM).

## Rollout Notes

- Zero-config change. The `SUMMARIZE_CONCURRENCY` env var already defaults to 8.
- Backward compatible: `concurrency=1` produces identical behavior to the old sequential loop.
- No migration needed. No database changes. No API changes.
- Monitor LLM API rate limits after deployment -- concurrent requests may hit provider rate limits sooner. Operators can reduce `SUMMARIZE_CONCURRENCY` if needed.
