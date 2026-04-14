# Feature Specification: Skip Upsert for Unchanged Chunks in StoreStep

**Feature Branch**: `story/1825-skip-upsert-unchanged-chunks`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Story alkemio#1825

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Skip redundant upserts for unchanged chunks (Priority: P1)

As a platform operator running incremental ingests, I want StoreStep to skip writing chunks that have not changed since the last ingest so that ChromaDB I/O is reduced by up to 98% on incremental updates, pipeline completion is faster for unchanged content, and wear on the vector store is minimized.

**Why this priority**: This is the sole user story for this feature. ChangeDetectionStep already identifies unchanged chunks and pre-loads their embeddings, and EmbedStep already skips chunks with pre-loaded embeddings. However, StoreStep still re-writes all chunks unconditionally. This is the last gap in the pipeline optimization chain.

**Independent Test**: Ingest a knowledge base with 100 chunks. Re-ingest without changes. Verify that StoreStep reports 0 chunks stored and logs that 100 unchanged chunks were skipped. Then change 5 chunks and re-ingest. Verify that only 5 chunks are stored and 95 are skipped.

**Acceptance Scenarios**:

1. **Given** a PipelineContext with `unchanged_chunk_hashes` populated from ChangeDetectionStep, **When** StoreStep executes, **Then** chunks whose `content_hash` is in `unchanged_chunk_hashes` are NOT passed to `KnowledgeStorePort.ingest()`.
2. **Given** a mix of changed and unchanged chunks in the pipeline, **When** StoreStep executes, **Then** only changed chunks are stored, and `context.chunks_stored` reflects the actual number written.
3. **Given** summary chunks (embedding_type="summary") or BoK chunks with `content_hash=None`, **When** StoreStep executes with populated `unchanged_chunk_hashes`, **Then** those chunks are always stored because `None` is never in the hash set.
4. **Given** `unchanged_chunk_hashes` is empty (first run or change detection disabled), **When** StoreStep executes, **Then** all embedded chunks are stored (identical to pre-change behavior).
5. **Given** unchanged chunks are skipped, **When** StoreStep completes, **Then** an INFO log message reports how many unchanged chunks were skipped.
6. **Given** chunks without embeddings exist alongside unchanged chunks, **When** StoreStep executes, **Then** the "skipped N chunks without embeddings" error only counts chunks genuinely lacking embeddings, not unchanged ones.

---

### Edge Cases

- When `content_hash` is `None` (summary/BoK chunks), the chunk passes the filter because `unchanged_chunk_hashes` is populated with chunk hash strings, so `None` does not match any unchanged hash.
- When `change_detection_ran` is `False`, `unchanged_chunk_hashes` is empty, so the filter has no effect and all embedded chunks are stored.
- When all chunks are unchanged, `chunks_stored` is 0 and no upsert calls are made.
- When a chunk has no embedding AND is in `unchanged_chunk_hashes`, both filters exclude it; the no-embedding error count correctly counts only that chunk (not double-counted).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: StoreStep MUST NOT call `KnowledgeStorePort.ingest()` for chunks whose `content_hash` is present in `context.unchanged_chunk_hashes`.
- **FR-002**: `context.chunks_stored` MUST reflect only the chunks that were actually written to the store, excluding unchanged chunks.
- **FR-003**: StoreStep MUST log at INFO level how many unchanged chunks were skipped when the count is greater than zero.
- **FR-004**: The "skipped N chunks without embeddings" error MUST count only chunks genuinely lacking embeddings, not unchanged chunks.
- **FR-005**: Summary chunks and BoK chunks (with `content_hash=None`) MUST always be stored regardless of `unchanged_chunk_hashes` contents.
- **FR-006**: When `unchanged_chunk_hashes` is empty, StoreStep MUST behave identically to pre-change code (full backward compatibility).

### Key Entities

- **PipelineContext.unchanged_chunk_hashes**: A `set[str]` populated by ChangeDetectionStep containing content hashes of chunks that have not changed since the last ingest. Used by StoreStep to filter out unchanged chunks.
- **Chunk.content_hash**: A `str | None` computed by ContentHashStep. SHA-256 hash of chunk content. `None` for summary and BoK chunks.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On incremental ingest with no content changes, StoreStep performs zero upsert calls (verified by unit test).
- **SC-002**: On incremental ingest with partial changes, only changed chunks are upserted (verified by unit test asserting `chunks_stored` equals changed count).
- **SC-003**: Summary and BoK chunks are never filtered out (verified by unit test).
- **SC-004**: All existing pipeline tests continue to pass without modification (backward compatibility).

## Assumptions

- `ChangeDetectionStep` correctly populates `PipelineContext.unchanged_chunk_hashes` before StoreStep executes. No changes to ChangeDetectionStep are needed.
- `EmbedStep` already correctly skips chunks with pre-loaded embeddings. No changes to EmbedStep are needed.
- The `Chunk` dataclass is not modified. The existing `unchanged_chunk_hashes` mechanism on PipelineContext is sufficient.
- The content-addressable ID scheme (`content_hash` as storage ID) remains unchanged.
