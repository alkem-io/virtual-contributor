# Specification: Skip upsert for unchanged chunks in StoreStep

**Story:** #1825
**Parent:** alkem-io/alkemio#1820

## User Value

Incremental ingest runs currently re-write all existing unchanged chunks to ChromaDB with identical content, metadata, and embeddings. For a knowledge base with 500 chunks where only 10 changed, 490 unnecessary upserts are performed. Filtering these out reduces ChromaDB I/O by up to 98% on incremental updates, speeds up pipeline completion for unchanged content, and reduces wear on the vector store.

## Scope

- Modify `StoreStep.execute()` in `core/domain/pipeline/steps.py` to filter out chunks whose `content_hash` appears in `context.unchanged_chunk_hashes` before upserting to ChromaDB.
- Ensure `IngestResult` and pipeline metrics correctly reflect the number of chunks actually stored versus skipped.
- Add unit tests proving the skip behavior works correctly.

## Out of Scope

- Adding a `changed: bool` flag to the `Chunk` dataclass (the `unchanged_chunk_hashes` set on `PipelineContext` already provides the mechanism).
- Changes to `ChangeDetectionStep` logic (it already correctly populates `unchanged_chunk_hashes`).
- Changes to `EmbedStep` (it already correctly skips chunks with pre-loaded embeddings).
- Performance benchmarking or profiling.
- Changes to the ChromaDB adapter itself.

## Acceptance Criteria

1. `StoreStep` does NOT call `ingest()` for chunks whose `content_hash` is in `context.unchanged_chunk_hashes`.
2. Summary chunks (embedding_type="summary") and BoK chunks are never filtered out (they have no content_hash in `unchanged_chunk_hashes`).
3. `context.chunks_stored` reflects only the chunks that were actually written, not the unchanged ones.
4. Logging indicates how many unchanged chunks were skipped.
5. All existing tests continue to pass.
6. New tests cover the skip-unchanged behavior end-to-end.

## Constraints

- Must not change the `Chunk` dataclass (use existing `unchanged_chunk_hashes` mechanism).
- Must preserve backward compatibility: when `change_detection_ran` is False or `unchanged_chunk_hashes` is empty, behavior is identical to current code.
- Must not break the content-addressable ID scheme (`content_hash` as storage ID).
