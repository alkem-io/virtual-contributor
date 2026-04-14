# Specification: Incremental Embedding — Embed Documents as They Finish Summarization

**Story:** #1826
**Parent:** alkem-io/alkemio#1820

## User Value

Reduce ingest pipeline wall-clock time by overlapping summarization (LLM-bound I/O) with embedding (GPU-bound I/O). Currently, all documents must complete summarization before any embedding begins. With incremental embedding, each document's chunks are embedded immediately after its summary is produced, eliminating the idle wait.

## Scope

- Modify `DocumentSummaryStep` to accept an `EmbeddingsPort` and embed each document's chunks (plus its summary chunk) immediately after summarization completes.
- Remove the standalone `EmbedStep` from the pipeline order for document/summary chunks (it still handles BoK summary chunks and any remaining un-embedded chunks as a safety net).
- Update both ingest plugins (`ingest_space`, `ingest_website`) to pass the `EmbeddingsPort` to `DocumentSummaryStep` and adjust pipeline step ordering.
- Ensure the `EmbedStep` remains in the pipeline as a catch-all for chunks not yet embedded (BoK summary, documents below the chunk threshold that skip summarization).
- Maintain full backward compatibility: no changes to the pipeline engine, pipeline context, or data models.

## Out of Scope

- Option B (background embedding worker with async queue) — deferred to a future story.
- Option C (streaming pipeline engine redesign) — deferred to a future story.
- Concurrent summarization across documents (covered by #1823).
- Changes to StoreStep, OrphanCleanupStep, ChangeDetectionStep, ContentHashStep, or ChunkStep.
- Changes to the pipeline engine (`IngestEngine`).

## Acceptance Criteria

1. After `DocumentSummaryStep` summarizes a document, that document's content chunks AND its summary chunk are embedded before moving to the next document.
2. `EmbedStep` skips chunks that already have embeddings (existing behavior), acting as a safety net for BoK summary and below-threshold documents.
3. Both `ingest_space` and `ingest_website` plugins use the updated `DocumentSummaryStep` with the embeddings port.
4. All existing tests pass without modification (except those that need updating for the new constructor parameter).
5. New unit tests verify: (a) chunks are embedded inline during summarization, (b) EmbedStep still handles remaining un-embedded chunks, (c) error in inline embedding is captured in context.errors without halting the pipeline.
6. No changes to the pipeline engine, context dataclass, or domain models.

## Constraints

- Python 3.12, async throughout.
- Must use existing `EmbeddingsPort` protocol — no new ports or adapters.
- `DocumentSummaryStep` constructor gains an optional `embeddings_port` parameter (default `None`) for backward compatibility.
- Batch size for inline embedding should match `EmbedStep` default (50).
- Error handling: per-document embedding errors are appended to `context.errors` but do not prevent summarization of subsequent documents.
