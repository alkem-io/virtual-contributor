# Plan: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Spec:** `spec.md`
**Date:** 2026-04-08

---

## 1. Architecture

The change is localized to a single pipeline step class (`DocumentSummaryStep`) and its wiring in one plugin. No new modules, adapters, or ports are introduced.

**Pattern:** Replace the sequential `for` loop in `DocumentSummaryStep.execute()` with semaphore-bounded `asyncio.gather`. Each document's summarization runs as an independent coroutine. Results are collected into a local list and batch-applied to the shared `PipelineContext` after all coroutines complete.

```
Before:  for doc in docs_to_summarize:
             summary = await _refine_summarize(...)
             context.document_summaries[doc_id] = summary
             context.chunks.append(summary_chunk)

After:   sem = asyncio.Semaphore(self._concurrency)

         async def _summarize_one(index, doc_id, doc_chunks) -> _SummaryResult | _SummaryError:
             async with sem:
                 summary = await _refine_summarize(...)
                 return _SummaryResult(index, doc_id, summary, summary_chunk)

         results = await asyncio.gather(*[_summarize_one(i, d, c) for i, (d, c) in enumerate(docs_to_summarize)])

         # Apply results in original order
         for result in sorted(results, key=lambda r: r.index):
             if isinstance(result, _SummaryResult):
                 context.document_summaries[result.doc_id] = result.summary
                 context.chunks.append(result.chunk)
             else:
                 context.errors.append(result.error_msg)
```

## 2. Affected Modules

| Module | Change | Risk |
|--------|--------|------|
| `core/domain/pipeline/steps.py` | Rewrite `DocumentSummaryStep.execute()` to use `asyncio.gather` with `Semaphore`. Add concurrency validation in `__init__`. | Medium: core logic change |
| `plugins/ingest_space/plugin.py` | Wire `concurrency=config.summarize_concurrency` when constructing `DocumentSummaryStep`. | Low: one-line addition |
| `tests/core/domain/test_pipeline_steps.py` | Add new tests for concurrency behavior, error isolation, and `concurrency=1` equivalence. | Low: additive |

## 3. Data Model Deltas

None. No changes to `Chunk`, `Document`, `DocumentMetadata`, `PipelineContext`, or `IngestResult`.

## 4. Interface Contracts

No interface changes. `DocumentSummaryStep` continues to satisfy the `PipelineStep` protocol:
- `name: str` property (unchanged)
- `async execute(context: PipelineContext) -> None` (signature unchanged)

Constructor signature unchanged: `__init__(llm_port, summary_length, concurrency, chunk_threshold)`. Only semantic change: `concurrency` is now actually used, and validated to be >= 1.

## 5. Test Strategy

| Test | Type | Purpose |
|------|------|---------|
| `test_concurrent_summarization_multiple_docs` | Unit | Verify multiple documents are processed concurrently (track call ordering) |
| `test_concurrency_one_is_sequential` | Unit | `concurrency=1` produces identical results to sequential |
| `test_concurrent_error_isolation` | Unit | One document's failure does not prevent others from completing |
| `test_results_applied_in_order` | Unit | Summary chunks appear in original document iteration order regardless of completion order |
| `test_concurrency_validation` | Unit | `concurrency=0` and negative values raise `ValueError` |
| Existing `TestDocumentSummaryStep` suite | Regression | All 6 existing tests pass unchanged |

## 6. Rollout Notes

- **Backward compatible:** `concurrency=1` is functionally identical to old sequential behavior.
- **Config already exists:** `SUMMARIZE_CONCURRENCY=8` is the default. No deployment changes needed.
- **No migration:** No data model or store schema changes.
- **Monitoring:** The `StepMetrics.duration` for `document_summary` step will show reduced wall time. Existing logging (`Summarizing document ...` / `Summarized document ...`) is preserved per-document.
