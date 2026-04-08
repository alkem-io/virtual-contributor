# Plan: Incremental Embedding After Summarization

**Story:** alkem-io/alkemio#1826
**Created:** 2026-04-08

## Architecture

The change follows Option A from the story: per-document embed after summary. The modification is entirely within the pipeline steps layer, requiring no changes to the pipeline engine, ports, adapters, or event models.

### Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` | Modify `DocumentSummaryStep.__init__` to accept optional `embeddings_port` and `embed_batch_size`. Add `_embed_document_chunks` helper method. Call it after each document summary. |
| `plugins/ingest_space/plugin.py` | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` constructor. |
| `plugins/ingest_website/plugin.py` | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` constructor. |
| `tests/core/domain/test_pipeline_steps.py` | Add new tests for incremental embedding behavior in `TestDocumentSummaryStep`. |

### Modules NOT Changed

- `core/domain/pipeline/engine.py` -- No engine changes needed.
- `core/domain/pipeline/__init__.py` -- No new exports.
- `core/ports/embeddings.py` -- Port interface unchanged.
- `core/domain/ingest_pipeline.py` -- Data models unchanged.
- `tests/conftest.py` -- Existing mock ports sufficient.

## Data Model Deltas

None. The `Chunk`, `Document`, `DocumentMetadata`, `IngestResult`, and `PipelineContext` dataclasses are unchanged. The only runtime difference is that `chunk.embedding` gets populated earlier (during DocumentSummaryStep instead of during EmbedStep).

## Interface Contracts

### DocumentSummaryStep Constructor (modified)

```python
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,  # NEW
    embed_batch_size: int = 50,                       # NEW
) -> None:
```

When `embeddings_port is None`: behavior identical to current (no incremental embedding).
When `embeddings_port is not None`: after each document summary, embeds that document's chunks + summary chunk.

### _embed_document_chunks helper (new private method)

```python
async def _embed_document_chunks(
    self,
    chunks: list[Chunk],
    context: PipelineContext,
    doc_id: str,
) -> None:
```

Filters to chunks needing embedding (`embedding is None`), batches them by `embed_batch_size`, calls `self._embeddings.embed(texts)`, and assigns embeddings. Errors are appended to `context.errors`.

## Test Strategy

1. **Unit test: incremental embedding after summary** -- Verify that after DocumentSummaryStep runs with an embeddings_port, all chunks for summarized documents have embeddings.
2. **Unit test: summary chunk gets embedded** -- Verify the summary chunk itself receives an embedding.
3. **Unit test: unchanged chunks not re-embedded** -- Pre-load embedding on a chunk, verify it is not sent to the embeddings port.
4. **Unit test: no embeddings_port means no embedding** -- Verify backward compat: without embeddings_port, chunks remain un-embedded after DocumentSummaryStep.
5. **Unit test: embedding error does not block summarization** -- Verify that if embedding fails, the summary still exists and errors are recorded.
6. **Integration test: full pipeline still produces correct results** -- Existing TestIngestEngine tests cover this; ensure they still pass.

## Rollout Notes

- This is a pure performance optimization. No configuration changes required.
- The feature activates automatically when both plugins pass embeddings_port to DocumentSummaryStep.
- Monitoring: the `document_summary` step's duration in metrics will now include embedding time for that step. The `embed` step's duration will decrease proportionally since most chunks are pre-embedded.
- Rollback: simply remove the `embeddings_port` parameter from the plugin pipeline assemblies to revert to batch embedding.
