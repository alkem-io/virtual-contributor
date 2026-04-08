# Spec: Incremental Embedding -- Embed Documents as They Finish Summarization

**Story:** alkem-io/alkemio#1826
**Date:** 2026-04-08

## User Value

Reduce ingest pipeline wall-clock time by overlapping summarization I/O (LLM-bound) with embedding I/O (GPU-bound). Currently, all chunks sit idle after their document's summary completes, waiting for every other document to finish summarization before embedding begins. Incremental embedding eliminates this idle time.

## Scope

- Modify `DocumentSummaryStep` to accept an `EmbeddingsPort` and embed each document's chunks immediately after that document's summary completes.
- The BoK summary chunk and any other summary chunks produced during summarization are also embedded incrementally within the same step.
- `EmbedStep` continues to exist and runs after `BodyOfKnowledgeSummaryStep` to embed any remaining chunks that were not embedded incrementally (e.g., chunks from documents below the summarization threshold, the BoK summary chunk itself, or documents that were skipped by change detection).
- No changes to the pipeline engine (`IngestEngine`) -- the step sequence remains ordered; the optimization is within `DocumentSummaryStep`.
- No changes to `PipelineContext`, `Chunk`, or `IngestResult` data models.
- No changes to `StoreStep`, `OrphanCleanupStep`, or `ChangeDetectionStep`.

## Out of Scope

- Streaming pipeline redesign (Option C from the issue).
- Background embedding worker / async queue (Option B from the issue).
- Concurrent summarization (covered by sibling story #1823).
- Changes to the pipeline engine's step execution model (remains sequential).

## Acceptance Criteria

1. After `DocumentSummaryStep` finishes summarizing a document, that document's content chunks and its summary chunk have embeddings set (not `None`).
2. `EmbedStep` skips chunks that already have embeddings (existing behavior), so no double-embedding occurs.
3. Pipeline produces identical final output (stored chunks, embeddings, summaries) as the current sequential approach.
4. Documents below the chunk threshold (not summarized) still get embedded by `EmbedStep` as before.
5. If embedding fails for a document's chunks during `DocumentSummaryStep`, the error is recorded in `context.errors` and the chunks are left without embeddings for `EmbedStep` to retry.
6. All existing tests continue to pass.
7. New tests cover the incremental embedding path: embedding happens per-document after summarization, EmbedStep correctly skips pre-embedded chunks.

## Constraints

- Must follow Option A (per-document embed after summary) as stated in the issue.
- Must maintain backward compatibility: `DocumentSummaryStep` with no `embeddings_port` argument must work identically to today (no embedding performed).
- Must preserve the duck-typed `PipelineStep` protocol -- no base class changes.
- Must not alter the `EmbeddingsPort` protocol.
