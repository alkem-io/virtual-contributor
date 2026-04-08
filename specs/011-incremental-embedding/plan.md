# Plan: Incremental Embedding

**Story:** alkem-io/alkemio#1826

---

## Architecture

The change follows **Option A** from the issue: per-document embedding after summary. No new classes, no new pipeline steps, no new ports. The modification is entirely within `DocumentSummaryStep` which gains an optional `EmbeddingsPort` dependency.

### Current Flow

```
ChunkStep -> ContentHashStep -> ChangeDetectionStep -> DocumentSummaryStep -> BodyOfKnowledgeSummaryStep -> EmbedStep -> StoreStep -> OrphanCleanupStep
```

Each step runs to completion before the next starts. DocumentSummaryStep summarizes all documents sequentially, then EmbedStep embeds all chunks in batch.

### New Flow

```
ChunkStep -> ContentHashStep -> ChangeDetectionStep -> DocumentSummaryStep(*) -> BodyOfKnowledgeSummaryStep -> EmbedStep(**) -> StoreStep -> OrphanCleanupStep
```

(*) DocumentSummaryStep now: for each document, (1) summarize, (2) embed that document's content chunks + summary chunk immediately.

(**) EmbedStep unchanged but naturally skips all already-embedded chunks (existing behavior at line 423).

---

## Affected Modules

| Module | Change Type | Description |
|--------|-------------|-------------|
| `core/domain/pipeline/steps.py` | Modify | `DocumentSummaryStep.__init__` gains `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50`. `execute()` embeds each document's chunks after summarization. |
| `plugins/ingest_space/plugin.py` | Modify | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep`. |
| `plugins/ingest_website/plugin.py` | Modify | Pass `embeddings_port=self._embeddings` to `DocumentSummaryStep`. |
| `tests/core/domain/test_pipeline_steps.py` | Modify | Add tests for incremental embedding in `TestDocumentSummaryStep`. |

---

## Data Model Deltas

None. `Chunk.embedding` already supports `list[float] | None`. No new fields, no schema changes.

---

## Interface Contracts

### DocumentSummaryStep.__init__ (updated)

```python
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,   # NEW
    embed_batch_size: int = 50,                        # NEW
) -> None:
```

- `embeddings_port=None`: backward compatible. When None, no incremental embedding occurs (existing behavior).
- `embed_batch_size=50`: matches EmbedStep default.

### _embed_document_chunks (new private helper)

```python
async def _embed_document_chunks(
    self,
    chunks: list[Chunk],
    context: PipelineContext,
) -> None:
```

Embeds a list of chunks using `self._embeddings`, batched by `self._embed_batch_size`. Errors are appended to `context.errors` without aborting.

---

## Test Strategy

| Test ID | Description | Type |
|---------|-------------|------|
| T-IE-1 | DocumentSummaryStep with embeddings_port embeds content chunks after each document summary | Unit |
| T-IE-2 | DocumentSummaryStep with embeddings_port embeds the summary chunk itself | Unit |
| T-IE-3 | DocumentSummaryStep without embeddings_port (None) does not embed -- backward compat | Unit |
| T-IE-4 | EmbedStep skips all chunks already embedded by DocumentSummaryStep | Unit (existing test covers this) |
| T-IE-5 | Embedding failure during DocumentSummaryStep does not prevent next document summarization | Unit |
| T-IE-6 | Below-threshold documents are not touched by DocumentSummaryStep incremental embedding | Unit |
| T-IE-7 | Full pipeline integration: chunks embedded exactly once across DocumentSummaryStep + EmbedStep | Integration |

---

## Rollout Notes

- Feature is automatically active when plugins pass `embeddings_port` to `DocumentSummaryStep`.
- No configuration flag needed; the feature activates by construction in the plugin wiring.
- Backward compatible: any external caller that does not pass `embeddings_port` gets existing behavior.
- No migration, no database changes, no new environment variables.
