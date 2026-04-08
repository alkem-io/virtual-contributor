# Plan: Incremental Embedding -- Embed Documents as They Finish Summarization

**Story:** alkem-io/alkemio#1826
**Date:** 2026-04-08

## Architecture

Option A from the issue: per-document embed after summary. No pipeline engine changes. The optimization is contained within `DocumentSummaryStep`.

### Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` | `DocumentSummaryStep.__init__` gains optional `embeddings_port` and `embed_batch_size`. `execute()` embeds a document's chunks + summary chunk immediately after summarizing that document. |
| `plugins/ingest_space/plugin.py` | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep`. |
| `plugins/ingest_website/plugin.py` | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep`. |
| `tests/core/domain/test_pipeline_steps.py` | New tests for incremental embedding behavior. |

### No Changes Required

- `core/domain/pipeline/engine.py` -- step execution model unchanged.
- `core/domain/pipeline/__init__.py` -- no new exports.
- `core/domain/ingest_pipeline.py` -- no model changes.
- `core/ports/embeddings.py` -- port protocol unchanged.
- `EmbedStep` -- unchanged; its `c.embedding is None` filter naturally skips pre-embedded chunks.
- `StoreStep`, `OrphanCleanupStep`, `ChangeDetectionStep` -- unchanged.

## Data Model Deltas

None. `Chunk.embedding` is already `list[float] | None`; it simply gets populated earlier.

## Interface Contracts

### DocumentSummaryStep.__init__ (updated)

```python
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,  # NEW
    embed_batch_size: int = 50,                      # NEW
) -> None:
```

When `embeddings_port` is not None, after summarizing each document:
1. Collect that document's content chunks (where `embedding is None`).
2. Collect the newly-created summary chunk.
3. Embed them all in batches of `embed_batch_size`.
4. On failure, log error to `context.errors`; leave chunks unembedded for `EmbedStep` fallback.

## Test Strategy

| Test | Purpose |
|------|---------|
| `test_incremental_embed_after_summary` | Given embeddings_port, after execute(), summarized documents' chunks have embeddings set. |
| `test_incremental_embed_summary_chunk` | The summary chunk itself is also embedded. |
| `test_no_embed_when_port_is_none` | Without embeddings_port, chunks remain unembedded (backward compat). |
| `test_incremental_embed_skips_preloaded` | Chunks with pre-loaded embeddings (from ChangeDetection) are not re-embedded. |
| `test_incremental_embed_error_recorded` | Embedding failure is recorded in context.errors; chunks left for EmbedStep retry. |
| `test_embed_step_skips_incrementally_embedded` | Integration: EmbedStep receives no work for already-embedded chunks. |
| `test_below_threshold_not_embedded_by_summary_step` | Documents below chunk_threshold are not embedded by DocumentSummaryStep. |

## Rollout Notes

- No configuration changes needed. The optimization activates when plugins pass `embeddings_port`.
- No migration needed. The pipeline output is identical.
- Performance: wall-clock improvement is proportional to the number of documents summarized. Each document's chunks start embedding as soon as its summary is done instead of waiting for all summaries.
