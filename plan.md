# Plan: Incremental Embedding

**Story:** #1826

## Architecture

**Approach: Option A — Per-document embed after summary (from the issue).**

The `DocumentSummaryStep` is extended with an optional `EmbeddingsPort`. After each document's summary is produced, the step immediately embeds that document's content chunks AND the newly created summary chunk. This overlaps LLM-bound summarization I/O with GPU-bound embedding I/O for the next document.

The existing `EmbedStep` remains in the pipeline as a safety net to handle:
- Chunks from documents below the chunk threshold (not summarized).
- The BoK summary chunk (produced by `BodyOfKnowledgeSummaryStep`, after summarization).
- Any chunks where inline embedding failed (retry semantics).

No changes to the pipeline engine, context, or domain models.

## Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` | `DocumentSummaryStep` gains `embeddings_port` param + inline embed logic |
| `plugins/ingest_space/plugin.py` | Pass `embeddings` to `DocumentSummaryStep` constructor |
| `plugins/ingest_website/plugin.py` | Pass `embeddings` to `DocumentSummaryStep` constructor |
| `tests/core/domain/test_pipeline_steps.py` | New tests for inline embedding; update existing `DocumentSummaryStep` tests |

## Data Model Deltas

None. No changes to `Chunk`, `Document`, `DocumentMetadata`, `IngestResult`, or `PipelineContext`.

## Interface Contracts

### `DocumentSummaryStep.__init__` (updated)

```python
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,
    embed_batch_size: int = 50,
) -> None:
```

- `embeddings_port`: When provided, enables inline embedding after each document's summary.
- `embed_batch_size`: Batch size for inline embedding calls. Default 50 (matches `EmbedStep`).

### Internal helper: `_embed_chunks`

A private async method on `DocumentSummaryStep` that embeds a list of chunks in batches, mirroring `EmbedStep.execute` logic but operating on a subset.

## Test Strategy

1. **Unit: inline embedding occurs** — Provide `MockEmbeddingsPort` to `DocumentSummaryStep`, verify chunks have embeddings after `execute`.
2. **Unit: EmbedStep skip** — After `DocumentSummaryStep` with inline embedding, verify `EmbedStep` skips already-embedded chunks.
3. **Unit: inline embed error handling** — Provide a failing embeddings port, verify errors are captured and summarization continues.
4. **Unit: no embeddings_port (backward compat)** — Construct `DocumentSummaryStep` without `embeddings_port`, verify behavior matches previous implementation.
5. **Unit: below-threshold documents** — Verify documents with <= chunk_threshold chunks are NOT embedded by `DocumentSummaryStep`.
6. **Integration: full pipeline** — Run the complete pipeline with inline embedding enabled, verify all chunks are stored with embeddings.

## Rollout Notes

- Backward compatible: `embeddings_port=None` preserves existing behavior.
- Both ingest plugins are updated simultaneously — no feature flag needed.
- No config changes, no new env vars, no infrastructure changes.
