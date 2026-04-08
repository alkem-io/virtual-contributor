# Spec: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

Reduce unnecessary ChromaDB I/O during incremental ingest runs by skipping upserts for chunks whose content, metadata, and embeddings have not changed since the last ingest. This directly improves pipeline throughput and reduces vector-store wear for knowledge bases with stable content.

## Scope

- Modify `StoreStep.execute()` in `core/domain/pipeline/steps.py` to filter out chunks whose `content_hash` appears in `context.unchanged_chunk_hashes` before upserting.
- Ensure summary chunks and BoK summary chunks (which do not participate in change detection) are always stored.
- Update logging to reflect the number of unchanged chunks skipped by StoreStep.

## Out of Scope

- Changes to `ChangeDetectionStep` -- it already correctly identifies unchanged chunks and pre-loads their embeddings.
- Adding a `changed: bool` field to the `Chunk` dataclass -- the `unchanged_chunk_hashes` set on `PipelineContext` is sufficient and avoids model changes.
- Changes to `EmbedStep` -- it already skips chunks with pre-loaded embeddings.
- Performance benchmarking or metrics instrumentation beyond existing logging.

## Acceptance Criteria

1. `StoreStep` does NOT call `upsert()` for chunks whose `content_hash` is present in `context.unchanged_chunk_hashes`.
2. `StoreStep` continues to store all chunks that have embeddings and are NOT in the unchanged set (new chunks, changed chunks, summary chunks).
3. The `chunks_stored` counter on `PipelineContext` only counts chunks that were actually written to the store.
4. A log message is emitted reporting the number of unchanged chunks skipped by StoreStep.
5. The skip-error message ("skipped N chunks without embeddings") no longer counts unchanged chunks as "skipped without embeddings."
6. All existing tests continue to pass.
7. New unit tests verify: (a) unchanged chunks are excluded from storage, (b) changed chunks with embeddings are stored, (c) summary chunks are always stored regardless of unchanged set, (d) chunks_stored counter accuracy.

## Constraints

- No changes to the `Chunk` dataclass or `PipelineContext` dataclass.
- Must remain backward-compatible: when `unchanged_chunk_hashes` is empty (no change detection ran, or all chunks are new), behavior is identical to current.
- Python 3.12, async, follows existing codebase conventions.
