# Feature Specification: Incremental Embedding

**Feature Branch**: `story/1826-incremental-embedding`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Story alkemio#1826 — "Incremental embedding — embed documents as they finish summarization"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Inline Embedding After Document Summarization (Priority: P1)

As a platform operator ingesting large spaces or websites, I want each document's chunks to be embedded immediately after its summary is produced, so that the pipeline overlaps LLM-bound summarization I/O with GPU-bound embedding I/O and reduces total ingest wall-clock time.

**Why this priority**: This is the sole user story and the entire purpose of the feature. Currently all documents must complete summarization before any embedding begins, creating idle time. Inline embedding eliminates this wait by pipelining the two I/O-bound phases.

**Independent Test**: Ingest a space with 10+ documents. Observe logs showing "Inline-embedded N/M chunks for document X" after each document summary. Verify that `EmbedStep` logs show it skipping already-embedded chunks. Compare total pipeline duration to a run without inline embedding.

**Acceptance Scenarios**:

1. **Given** `DocumentSummaryStep` is constructed with an `embeddings_port`, **When** a document's summary is produced, **Then** that document's content chunks AND its summary chunk are embedded before the next document is summarized.
2. **Given** `DocumentSummaryStep` is constructed without `embeddings_port` (None), **When** summarization runs, **Then** behavior is identical to the previous implementation (no inline embedding).
3. **Given** inline embedding fails for a specific document, **When** the error occurs, **Then** the error is recorded in `context.errors` and summarization continues for subsequent documents.
4. **Given** chunks already have embeddings (e.g., from `ChangeDetectionStep`), **When** inline embedding runs, **Then** those chunks are skipped.
5. **Given** `EmbedStep` runs after `DocumentSummaryStep` with inline embedding, **When** all document chunks were already embedded inline, **Then** `EmbedStep` makes zero embed calls for those chunks (safety-net behavior).
6. **Given** a document has fewer chunks than `chunk_threshold`, **When** `DocumentSummaryStep` runs, **Then** that document is skipped (no summary, no inline embedding).

---

### Edge Cases

- When inline embedding fails for one document but succeeds for others, only the failed document's chunks remain un-embedded. `EmbedStep` picks them up as a safety net.
- When all documents are below `chunk_threshold`, no summaries and no inline embeddings are produced. `EmbedStep` handles all embedding.
- When `embed_batch_size` exceeds the number of chunks for a document, all chunks are embedded in a single batch call.
- When `embeddings_port` is provided but no documents exceed `chunk_threshold`, the embeddings port is never called.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `DocumentSummaryStep` MUST accept an optional `embeddings_port: EmbeddingsPort | None` constructor parameter (default `None`) for backward compatibility.
- **FR-002**: `DocumentSummaryStep` MUST accept an optional `embed_batch_size: int` constructor parameter (default 50) matching `EmbedStep` defaults.
- **FR-003**: When `embeddings_port` is provided, `DocumentSummaryStep` MUST embed each document's content chunks and its summary chunk immediately after summarization completes.
- **FR-004**: `DocumentSummaryStep` MUST skip chunks that already have embeddings during inline embedding.
- **FR-005**: Per-document embedding errors MUST be appended to `context.errors` without halting summarization of subsequent documents.
- **FR-006**: `EmbedStep` MUST continue to skip chunks that already have embeddings (existing behavior), acting as a safety net for BoK summary chunks, below-threshold documents, and any failed inline embeddings.
- **FR-007**: Both `ingest_space` and `ingest_website` plugins MUST pass their `embeddings_port` to `DocumentSummaryStep`.
- **FR-008**: No changes MUST be made to the pipeline engine (`IngestEngine`), `PipelineContext`, or domain models.

### Key Entities

- **DocumentSummaryStep**: Extended with optional `embeddings_port` and `embed_batch_size` to support inline embedding after each document's summarization.
- **EmbedStep**: Unchanged; continues to act as safety net for any un-embedded chunks.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After `DocumentSummaryStep` with `embeddings_port`, all summarized documents' content and summary chunks have embeddings.
- **SC-002**: `EmbedStep` makes zero embed calls for chunks already embedded inline by `DocumentSummaryStep`.
- **SC-003**: An inline embedding failure for one document does not prevent summarization or embedding of other documents.
- **SC-004**: Constructing `DocumentSummaryStep` without `embeddings_port` produces identical behavior to the pre-change implementation.

## Assumptions

- The existing `EmbeddingsPort` protocol supports the `embed(texts: list[str]) -> list[list[float]]` interface needed for inline embedding.
- Batch size of 50 (matching `EmbedStep`) is appropriate for inline embedding without excessive memory usage.
- The `EmbedStep` already skips chunks with existing embeddings, requiring no changes to serve as a safety net.
- No changes to the pipeline engine or context dataclass are needed; `DocumentSummaryStep` operates within the existing step contract.
