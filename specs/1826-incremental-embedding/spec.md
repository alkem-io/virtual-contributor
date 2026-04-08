# Spec: Incremental Embedding -- Embed Documents as They Finish Summarization

**Story:** alkem-io/alkemio#1826
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

Reduces ingest pipeline wall-clock time by overlapping summarization I/O (LLM-bound) with embedding I/O (GPU/API-bound). Currently, all chunks wait idle after their document is summarized until every document finishes before the global EmbedStep runs. For a 15-document corpus where doc 1 finishes at minute 2, its chunks sit idle for 20+ minutes. Incremental embedding eliminates this wasted wait, reducing total ingest from 30+ minutes toward under 10 minutes (combined with concurrent summarization from #1823).

## Scope

1. Modify `DocumentSummaryStep` to accept an `EmbeddingsPort` and embed each document's chunks immediately after its summary is produced.
2. Ensure the existing global `EmbedStep` gracefully handles partially-embedded chunk lists (it already skips chunks with `embedding is not None` -- verify and preserve this behavior).
3. Both ingest plugin pipelines (`ingest_space`, `ingest_website`) gain the benefit automatically since they compose the same steps.
4. No changes to the pipeline engine (`IngestEngine`) -- this is Option A from the issue (per-document embed after summary), the simplest approach that delivers most of the benefit.
5. Add metrics/logging for the incremental embedding within `DocumentSummaryStep`.

## Out of Scope

- Background embedding task (Option B) -- more complex, deferred.
- Streaming pipeline redesign (Option C) -- architectural, deferred.
- Concurrent summarization (#1823) -- separate story, orthogonal.
- Changes to `StoreStep` -- chunks are stored after all embedding is complete, same as today.
- Changes to `BodyOfKnowledgeSummaryStep` -- the BoK summary chunk will still be embedded by the global `EmbedStep`.

## Acceptance Criteria

1. After each document summary is produced in `DocumentSummaryStep`, that document's content chunks plus its new summary chunk are embedded immediately.
2. The global `EmbedStep` still runs after all summarization and embeds any remaining chunks (e.g., chunks from documents below the chunk threshold that were not summarized, and the BoK summary chunk).
3. Total pipeline wall-clock time is reduced when multiple documents are present (overlap of summarization and embedding).
4. No change in the final embedded/stored output -- the same chunks with the same embeddings are stored as before (deterministic output).
5. Existing tests pass without modification; new tests cover the incremental embedding behavior.
6. Logging indicates per-document embedding progress within `DocumentSummaryStep`.

## Constraints

- Must remain backward-compatible: if `embeddings_port` is not provided to `DocumentSummaryStep`, it operates as before (no embedding).
- The `EmbedStep.execute()` method already skips chunks where `embedding is not None` -- this is the interlock that prevents double-embedding.
- Must not change the `PipelineStep` protocol or `PipelineContext` dataclass.
- Must not introduce new dependencies beyond what is already in the project.
