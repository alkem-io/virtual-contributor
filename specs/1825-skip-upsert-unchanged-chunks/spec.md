# Spec: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825
**Parent:** alkem-io/alkemio#1820
**Status:** Draft
**Date:** 2026-04-08

---

## User Value

Ingest pipeline runs for knowledge bases with mostly unchanged content currently waste significant ChromaDB I/O by re-writing every chunk on every run. This fix eliminates unnecessary upserts for unchanged chunks, reducing vector store I/O by up to 98% on incremental updates and improving pipeline throughput.

## Scope

- Modify `StoreStep.execute()` in `core/domain/pipeline/steps.py` to filter out chunks whose `content_hash` is present in `context.unchanged_chunk_hashes`.
- Add logging to record how many chunks were skipped due to being unchanged.
- Add unit tests verifying the filtering behavior.
- Update `IngestResult` reporting to account for unchanged-but-not-stored chunks.

## Out of Scope

- Adding a `changed: bool` flag to `Chunk` (alternative approach mentioned in issue, not adopted).
- Changes to `ChangeDetectionStep` logic (already works correctly).
- Changes to `EmbedStep` (already correctly skips chunks with pre-loaded embeddings).
- Performance benchmarking or metrics dashboards.

## Acceptance Criteria

1. **AC-1:** `StoreStep` does NOT call `upsert()` for chunks whose `content_hash` appears in `context.unchanged_chunk_hashes`.
2. **AC-2:** `StoreStep` continues to upsert all chunks that are genuinely new or changed (embedding present, hash not in unchanged set).
3. **AC-3:** Summary chunks (embedding_type="summary") are always stored regardless of unchanged_chunk_hashes (they have no content_hash-based dedup).
4. **AC-4:** A log message records the number of unchanged chunks skipped by StoreStep.
5. **AC-5:** `chunks_stored` counter on PipelineContext only counts actually stored chunks (not skipped ones).
6. **AC-6:** Unit tests cover: (a) unchanged chunks filtered out, (b) changed chunks still stored, (c) mixed scenario, (d) no regression when change detection did not run.
7. **AC-7:** All existing tests continue to pass.

## Constraints

- Must not introduce new dependencies.
- Must preserve backward compatibility: when `unchanged_chunk_hashes` is empty (e.g. change detection disabled or first run), all chunks with embeddings are stored as before.
- Filter must operate on `content_hash` membership in `unchanged_chunk_hashes`, not on embedding equality or other heuristics.
