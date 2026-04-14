# Feature Specification: Handle Empty Corpus Re-Ingestion

**Feature Branch**: `story/35-handle-empty-corpus-reingestion-cleanup`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Story #35: "Handle empty corpus re-ingestion -- run cleanup when source returns zero documents"

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Empty Space Cleanup (Priority: P1)

As a platform operator, I want all previously stored chunks to be deleted from the vector knowledge store when a space that previously had content now returns zero documents (e.g., the space was emptied), so that users querying the virtual contributor do not receive answers grounded in outdated or deleted content.

**Why this priority**: Without cleanup on empty fetch, stale chunks remain indefinitely in the knowledge store after content deletion, violating data integrity expectations. This is the most common scenario (space content removed via Alkemio UI).

**Independent Test**: Pre-populate a collection with chunks, then trigger an ingest-space event for a space that returns zero documents. Verify all pre-existing chunks are deleted and the plugin returns success.

**Acceptance Scenarios**:

1. **Given** a collection with previously stored chunks and `read_space_tree()` returns an empty list, **When** `IngestSpacePlugin.handle()` processes the event, **Then** the cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) runs and all pre-existing content chunks are deleted (BoK summary cleanup is out of scope -- see Edge Cases).
2. **Given** `read_space_tree()` returns an empty list, **When** the cleanup pipeline completes without errors, **Then** the plugin returns `result="success"`.
3. **Given** `read_space_tree()` returns an empty list, **When** the cleanup pipeline encounters errors, **Then** the plugin returns `result="failure"` with error details.
4. **Given** `read_space_tree()` raises an exception (e.g., GraphQL connection failure), **When** the plugin catches the exception, **Then** it returns `result="failure"` without running any cleanup pipeline (existing behavior preserved).

---

### User Story 2 -- Empty Website Cleanup (Priority: P1)

As a platform operator, I want all previously stored chunks to be deleted from the vector knowledge store when a website crawl succeeds but produces zero documents (e.g., the website went offline, or all pages have no extractable text), so that stale website content is removed.

**Why this priority**: Same data integrity concern as User Story 1, but for the website ingestion path. Both paths must be fixed together for consistent behavior.

**Independent Test**: Pre-populate a collection with website chunks, then trigger an ingest-website event where the crawl returns zero pages (or pages with empty text). Verify all pre-existing chunks are deleted and the plugin returns success.

**Acceptance Scenarios**:

1. **Given** a collection with previously stored chunks and `crawl()` returns an empty list, **When** `IngestWebsitePlugin.handle()` processes the event, **Then** the cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) runs and all pre-existing content chunks are deleted (BoK summary cleanup is out of scope -- see Edge Cases).
2. **Given** `crawl()` returns pages but text extraction produces zero documents (all empty/whitespace), **When** the plugin processes the event, **Then** the cleanup pipeline runs and all pre-existing chunks are deleted.
3. **Given** the crawl+extract pipeline produces zero documents, **When** the cleanup pipeline completes without errors, **Then** the plugin returns `result=IngestionResult.SUCCESS`.
4. **Given** `crawl()` raises an exception (e.g., connection timeout), **When** the plugin catches the exception, **Then** it returns `result=IngestionResult.FAILURE` without running any cleanup pipeline (existing behavior preserved).

---

### User Story 3 -- Observability for Empty Corpus Cleanup (Priority: P2)

As a platform operator, I want info-level log messages emitted when a cleanup pipeline runs on empty corpus, so that I can monitor and understand when stale data is being cleaned up.

**Why this priority**: Observability is important but secondary to the core cleanup behavior. Operators need visibility into when cleanup runs.

**Independent Test**: Trigger an empty-corpus ingest event and verify that an INFO-level log message appears before the cleanup pipeline runs, including the collection name and source identifier.

**Acceptance Scenarios**:

1. **Given** `read_space_tree()` returns `[]`, **When** the cleanup pipeline is about to run, **Then** an INFO log message is emitted containing the space ID and collection name.
2. **Given** `crawl()` produces zero documents, **When** the cleanup pipeline is about to run, **Then** an INFO log message is emitted containing the website base URL and collection name.

---

### Edge Cases

- When `read_space_tree()` returns `[]` because the space has no content or was not found: treated as empty-but-successful (not a failure). The GraphQL query succeeded; empty results mean zero documents should exist in the store.
- When `crawl()` returns pages but text extraction produces zero documents: treated as empty-but-successful. Zero usable documents means stale chunks should be removed.
- BoK summary chunk (`documentId="body-of-knowledge-summary"`) cleanup on empty corpus: this is a pre-existing gap. The BoK summary chunk has `embeddingType="summary"` and is not tracked in `removed_document_ids` by the current change detection logic. Out of scope for this story.
- The cleanup pipeline only runs `ChangeDetectionStep` + `OrphanCleanupStep` -- no `ChunkStep`, `ContentHashStep`, `EmbedStep`, `StoreStep`, or summarization steps are needed because there are no documents to process.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run a cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) when `IngestSpacePlugin` receives an event and `read_space_tree()` returns an empty list, deleting all previously stored chunks in the collection.
- **FR-002**: System MUST run a cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) when `IngestWebsitePlugin` receives an event and the crawl+extract pipeline produces zero documents, deleting all previously stored chunks in the collection.
- **FR-003**: System MUST return a success result from both plugins when the empty-but-successful cleanup pipeline completes without errors. `IngestSpacePlugin` returns `result="success"` (plain string). `IngestWebsitePlugin` returns `result=IngestionResult.SUCCESS` (enum, wire value `"success"`).
- **FR-004**: System MUST return a failure result from both plugins when the cleanup pipeline encounters errors, including error details in the response. `IngestSpacePlugin` returns `result="failure"` with `error=ErrorDetail(...)`. `IngestWebsitePlugin` returns `result=IngestionResult.FAILURE` with `error=str`.
- **FR-005**: System MUST preserve the existing failure behavior when `read_space_tree()` raises an exception -- return failure without running any cleanup pipeline.
- **FR-006**: System MUST preserve the existing failure behavior when `crawl()` raises an exception -- return failure without running any cleanup pipeline.
- **FR-007**: System MUST emit an INFO-level log message before running the cleanup pipeline, including the source identifier (space ID or website base URL) and collection name.
- **FR-008**: System MUST use the same `IngestEngine` orchestration for the cleanup pipeline as the full pipeline for consistency and metrics tracking.
- **FR-009**: System MUST NOT introduce new dependencies -- reuse existing pipeline steps.
- **FR-010**: System MUST NOT change the collection name derivation logic -- the cleanup pipeline uses the same collection name as the full pipeline.

### Key Entities

- **Cleanup Pipeline**: A minimal `IngestEngine` instance with only `ChangeDetectionStep` and `OrphanCleanupStep`, run against an empty document list to identify and delete all orphaned chunks.
- **Empty-But-Successful Fetch**: A fetch/crawl operation that completes without exceptions but returns zero documents. Distinguished from fetch failure (exception raised).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: When a space or website that previously had content returns zero documents on re-ingestion, all previously stored chunks are deleted from the knowledge store within the same ingestion event.
- **SC-002**: The empty-but-successful scenario returns `result="success"` and does not leave stale data in the knowledge store.
- **SC-003**: Fetch/crawl failures (exceptions) continue to return `result="failure"` without modifying the knowledge store.
- **SC-004**: Unit tests cover both the empty-successful and failure scenarios for each plugin, with assertions on both return values and knowledge store side effects.
- **SC-005**: All pre-existing tests continue to pass with zero modifications to existing test assertions.

## Assumptions

- The existing `ChangeDetectionStep` and `OrphanCleanupStep` already correctly handle an empty incoming document list -- all existing document IDs in the store will appear in `removed_document_ids`.
- The `IngestEngine` can be instantiated with a minimal step list (only 2 steps) without issues.
- No changes are needed to pipeline step implementations (`steps.py`), event models, wire format, crawlers, space readers, or HTML parsers.
- The BoK summary chunk cleanup gap is orthogonal and pre-existing; it is not addressed in this story.

## Clarifications

### Iteration 1

| # | Ambiguity | Chosen Answer | Rationale |
|---|-----------|--------------|-----------|
| C1 | Does "empty-but-successful" include cases where the crawl returned pages but text extraction produced zero documents? | Yes. Zero usable documents means stale chunks should be removed. | The purpose is to clean up stale content regardless of why no documents were produced. |
| C2 | Is `read_space_tree()` returning `[]` a failure or empty-but-successful? | Always empty-but-successful. Exceptions from the GraphQL layer indicate actual failures. | The GraphQL query succeeded. Empty content means zero documents should exist in the store. |
| C3 | Will the BoK summary chunk be cleaned up when the corpus becomes empty? | No -- pre-existing gap, out of scope. | Keeping scope tight. The gap is orthogonal. |
| C4 | Does the cleanup pipeline need summarization steps? | No. Only `ChangeDetectionStep` + `OrphanCleanupStep`. | Minimal pipeline; no summarization needed for empty corpus. |
| C5 | Should the empty-but-successful scenario be logged? | Yes, INFO-level log before running the cleanup pipeline. | Observability for operators. |
