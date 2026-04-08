# Plan: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Spec:** spec.md
**Date:** 2026-04-08

---

## Architecture

The change is localized to `DocumentSummaryStep.execute()` in `core/domain/pipeline/steps.py`. The sequential `for` loop (lines 281-313) is replaced with a concurrent pattern:

1. A per-document inner coroutine `_summarize_one(doc_id, doc_chunks)` that:
   - Acquires the semaphore
   - Calls `_refine_summarize()`
   - Returns a structured result (success data or error message)
2. `asyncio.gather()` dispatches all coroutines
3. After gather completes, results are batch-applied to `context.chunks`, `context.document_summaries`, and `context.errors`

This pattern avoids interleaved mutation of shared state and is idiomatic for asyncio concurrency.

## Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` | Rewrite `DocumentSummaryStep.execute()` to use `asyncio.Semaphore` + `asyncio.gather` |
| `plugins/ingest_space/plugin.py` | Pass `concurrency=` to `DocumentSummaryStep` for config consistency |
| `tests/core/domain/test_pipeline_steps.py` | Add concurrency-specific tests |

## Data Model Deltas

None. `PipelineContext` and `Chunk` are unchanged.

## Interface Contracts

`DocumentSummaryStep.__init__` signature is unchanged. The `concurrency` parameter already exists and is already wired from `SUMMARIZE_CONCURRENCY` config. The `execute()` method signature is unchanged (still `async def execute(self, context: PipelineContext) -> None`).

## Implementation Detail

```
# Pseudocode for the new execute() method:

async def execute(self, context):
    # 1. Build list of (doc_id, doc_chunks) to summarize (unchanged filter logic)
    docs_to_summarize = [...]

    # 2. Define result type
    @dataclass
    class _SummaryResult:
        doc_id: str
        summary: str
        summary_chunk: Chunk
    
    # 3. Define per-doc coroutine with semaphore
    sem = asyncio.Semaphore(self._concurrency)
    results: list[_SummaryResult] = []
    errors: list[str] = []

    async def _summarize_one(doc_id, doc_chunks):
        async with sem:
            summary = await _refine_summarize(...)
            return _SummaryResult(doc_id, summary, Chunk(...))

    # 4. Gather with per-coroutine error handling
    tasks = [_summarize_one(d, c) for d, c in docs_to_summarize]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 5. Batch-apply results
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            context.errors.append(...)
        else:
            context.document_summaries[outcome.doc_id] = outcome.summary
            context.chunks.append(outcome.summary_chunk)
```

Note: Using `return_exceptions=True` in gather so that one doc failure does not cancel others. Each coroutine still has its own try/except for logging, but `return_exceptions=True` provides a safety net.

## Test Strategy

1. **Existing tests pass unchanged:** The 6 existing `TestDocumentSummaryStep` tests must pass without modification.
2. **New concurrency tests:**
   - `test_concurrent_multiple_documents`: 3+ documents processed, all get summaries
   - `test_concurrent_error_isolation`: One document fails, others succeed
   - `test_concurrency_parameter_respected`: Verify semaphore limits concurrent access
   - `test_concurrent_results_applied_to_context`: Verify `document_summaries` dict and `chunks` list are correctly populated

## Rollout Notes

- No config changes needed -- `SUMMARIZE_CONCURRENCY` already exists (default 8).
- No migration needed -- this is a pure behavioral change (sequential -> concurrent).
- Backward compatible -- `concurrency=1` yields sequential behavior.
