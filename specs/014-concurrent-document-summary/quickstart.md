# Quickstart: Concurrent Document Summarization in DocumentSummaryStep

**Feature Branch**: `story/1823-implement-actual-concurrency-in-document-summary-step`
**Date**: 2026-04-14

## What This Feature Does

Replaces the sequential document summarization loop in `DocumentSummaryStep` with true concurrent execution using `asyncio.Semaphore` + `asyncio.gather`. The `concurrency` constructor parameter (default: 8) was already accepted but never used --- it now controls the maximum number of documents summarized in parallel.

For ingest workloads with many qualifying documents, this delivers 5-10x speedup with no configuration changes required.

## How It Works

1. Documents qualifying for summarization (>= `chunk_threshold` chunks, changed since last ingest) are identified
2. An `asyncio.Semaphore(concurrency)` bounds the number of concurrent summarizations
3. All qualifying documents are dispatched concurrently via `asyncio.gather`
4. Each concurrent task returns a `_SummaryResult` (summary + chunk on success, error message on failure)
5. After all tasks complete, results are applied to `PipelineContext` in original input order

## Configuration

No new environment variables. The existing `concurrency` parameter on `DocumentSummaryStep` (default: 8) now controls actual parallel execution. This parameter is set in the pipeline wiring in ingest plugins.

## Quick Verification

### 1. Run the concurrency tests

```bash
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestDocumentSummaryStepConcurrency -v
```

Expected output: 6 tests pass, including:
- `test_concurrent_execution_faster_than_sequential` --- timing-based concurrency proof
- `test_deterministic_ordering_of_summary_chunks` --- output order matches input order
- `test_partial_failure_does_not_block_other_documents` --- failure isolation
- `test_concurrency_one_produces_correct_results` --- sequential fallback
- `test_multiple_documents_all_summarized` --- completeness
- `test_no_context_corruption_under_concurrency` --- state integrity

### 2. Run the full test suite

```bash
poetry run pytest tests/core/domain/test_pipeline_steps.py -v
```

All existing tests continue to pass alongside the new concurrency tests.

### 3. Ingest a multi-document space

```bash
export PLUGIN_TYPE=ingest-space
poetry run python main.py
```

Observe logs showing multiple "Summarizing document ..." messages appearing concurrently rather than sequentially.

## Files Changed

| File | Change |
|------|--------|
| `core/domain/pipeline/steps.py` | Add `_SummaryResult` dataclass; refactor `DocumentSummaryStep.execute()` from sequential for-loop to `asyncio.Semaphore` + `asyncio.gather` with collect-and-apply pattern |
| `tests/core/domain/test_pipeline_steps.py` | Add `TestDocumentSummaryStepConcurrency` class (6 tests), `_DelayedLLMPort`, `_SelectiveFailLLMPort`, `_make_multi_doc_context` helpers |

## Contracts

No external interface changes:
- **LLMPort**: Unchanged
- **PluginContract**: Unchanged
- **Event schemas**: Unchanged
- **PipelineContext**: Same structure, same fields, same semantics
