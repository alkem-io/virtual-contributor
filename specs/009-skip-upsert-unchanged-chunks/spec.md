# Spec: Skip Upsert for Unchanged Chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

Reduce unnecessary ChromaDB I/O during incremental ingest runs. When a knowledge base with N chunks is re-ingested and only a small subset has changed, the system should only write the changed chunks to the vector store, not all N chunks. This directly reduces pipeline execution time and vector store load.

## Scope

- Modify `StoreStep.execute()` in `core/domain/pipeline/steps.py` to filter out chunks whose `content_hash` appears in `context.unchanged_chunk_hashes`.
- Ensure summary chunks (embedding_type="summary") and BoK summary chunks are always stored (they are regenerated each run when documents change).
- Update the `chunks_stored` counter to reflect only actually-written chunks.
- Add logging to report how many chunks were skipped due to being unchanged.
- Add unit tests proving the filtering works correctly.

## Out of Scope

- Changes to `ChangeDetectionStep` -- it already correctly populates `unchanged_chunk_hashes`.
- Changes to the `Chunk` dataclass (no new `changed: bool` flag -- the existing `unchanged_chunk_hashes` set is sufficient).
- Changes to `EmbedStep` -- it already skips chunks with pre-loaded embeddings.
- Changes to `OrphanCleanupStep`.
- Performance benchmarking or metrics dashboards.

## Acceptance Criteria

1. `StoreStep` does NOT call `upsert()` for content chunks whose `content_hash` is in `context.unchanged_chunk_hashes`.
2. `StoreStep` DOES call `upsert()` for changed content chunks, summary chunks, and BoK summary chunks.
3. `context.chunks_stored` reflects only the count of chunks actually written to the store.
4. A log message reports how many unchanged chunks were skipped during the store step.
5. All existing tests continue to pass.
6. New unit tests cover: (a) unchanged chunks are skipped, (b) changed chunks are stored, (c) summary chunks are always stored even when content chunks are unchanged, (d) mixed scenario with both changed and unchanged chunks.

## Constraints

- The fix must be backwards-compatible: if `unchanged_chunk_hashes` is empty (change detection did not run or found no unchanged chunks), all chunks with embeddings are stored as before.
- No new fields on `Chunk` or `PipelineContext` dataclasses.
- The filtering logic must be in `StoreStep` only -- no changes to upstream steps.
