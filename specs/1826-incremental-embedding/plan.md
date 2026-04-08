# Plan: Incremental Embedding

**Story:** alkem-io/alkemio#1826
**Date:** 2026-04-08

## Architecture

**Approach:** Option A from the issue -- per-document embed after summary. This is the simplest approach that delivers the majority of the performance benefit.

**Key insight:** Summarization is LLM-bound (CPU/network to LLM API) while embedding is GPU/API-bound (different resource). By interleaving them, we overlap I/O on different resources, reducing wall-clock time.

**Design:**
- `DocumentSummaryStep` gains an optional `EmbeddingsPort` dependency. When provided, after each document's summary is produced, it immediately embeds that document's content chunks (those without embeddings) plus the new summary chunk.
- The existing `EmbedStep` remains in the pipeline as a catch-all for any chunks not yet embedded (below-threshold documents, BoK summary, any chunks that failed incremental embedding).
- No changes to `PipelineContext`, `PipelineStep` protocol, or `IngestEngine`.

## Affected Modules

| Module | Change Type | Description |
|--------|------------|-------------|
| `core/domain/pipeline/steps.py` | Modify | Add `embeddings_port` and `embed_batch_size` params to `DocumentSummaryStep.__init__`. Add embedding logic after each document's summary loop. |
| `plugins/ingest_space/plugin.py` | Modify | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` constructor. |
| `plugins/ingest_website/plugin.py` | Modify | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` constructor. |
| `tests/core/domain/test_pipeline_steps.py` | Modify | Add tests for incremental embedding behavior. |

## Data Model Deltas

None. No changes to `PipelineContext`, `Chunk`, `Document`, `DocumentMetadata`, or `IngestResult`.

## Interface Contracts

### DocumentSummaryStep.__init__ (modified)

```python
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,  # NEW
    embed_batch_size: int = 50,  # NEW
) -> None:
```

- `embeddings_port`: When provided, enables incremental embedding after each document summary.
- `embed_batch_size`: Batch size for embedding calls within DocumentSummaryStep. Default 50 matches EmbedStep default.

### Behavioral contract

1. After each document summary is produced, if `embeddings_port` is set:
   a. Collect all content chunks for that document that lack embeddings.
   b. Include the newly created summary chunk.
   c. Embed them in batches of `embed_batch_size`.
   d. On error: log, append to `context.errors`, leave chunks without embeddings. Continue.
2. If `embeddings_port` is None: behavior is identical to current (no embedding).

## Test Strategy

1. **Unit test -- incremental embedding happens:** Provide embeddings_port to DocumentSummaryStep. Verify that after execution, the document's content chunks AND summary chunk have embeddings.
2. **Unit test -- no embedding without port:** Construct DocumentSummaryStep without embeddings_port. Verify chunks do NOT have embeddings after execution (same as current behavior).
3. **Unit test -- error resilience:** Provide a failing embeddings_port. Verify summarization still succeeds, error is recorded, chunks lack embeddings.
4. **Unit test -- EmbedStep skips already-embedded:** Run DocumentSummaryStep with embeddings_port, then run EmbedStep. Verify EmbedStep only embeds chunks that were not already embedded (e.g., below-threshold documents).
5. **Integration test -- full pipeline:** Run the full pipeline with DocumentSummaryStep+embeddings_port and EmbedStep. Verify same final output as without incremental embedding.
6. **Existing tests pass:** All existing TestDocumentSummaryStep tests pass unchanged (they don't pass embeddings_port, so behavior is unchanged).

## Rollout Notes

- Feature is opt-in via the `embeddings_port` parameter. Both plugins will be updated to pass it.
- No configuration changes needed -- the feature activates when the plugin passes the embeddings port.
- No migration or data changes.
- Logging within DocumentSummaryStep will indicate when incremental embedding occurs.
