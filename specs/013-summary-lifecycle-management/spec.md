# Feature Specification: Summary Lifecycle Management

**Feature Branch**: `story/36-summary-lifecycle-cleanup`
**Created**: 2026-04-14
**Status**: Implemented
**Input**: Story #36 -- Clean up stale summaries and BoK on edge cases

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Stale Per-Document Summary Cleanup (Priority: P1)

As a platform operator, I want stale per-document summaries to be automatically cleaned up when a previously summarized document drops below the summary threshold during re-ingestion, so that RAG retrieval does not surface outdated summary content that no longer reflects the current corpus.

**Why this priority**: Stale summaries directly mislead RAG retrieval by providing outdated content for documents that no longer qualify for summarization. This is the more common edge case (individual document edits reducing content) and has a higher impact on answer quality.

**Independent Test**: Ingest a document with enough content to generate a summary (>= 4 chunks). Re-ingest the same document with reduced content (< 4 chunks). Verify the old summary entry is deleted from the knowledge store.

**Acceptance Scenarios**:

1. **Given** change detection has run and a changed document now has fewer chunks than `chunk_threshold`, **When** `DocumentSummaryStep` executes, **Then** `f"{doc_id}-summary-0"` is added to `context.orphan_ids` for cleanup by `OrphanCleanupStep`.
2. **Given** a changed document still has chunks above or equal to `chunk_threshold`, **When** `DocumentSummaryStep` executes, **Then** the document is summarized normally and no orphan ID is added.
3. **Given** change detection did not run (`change_detection_ran` is False), **When** `DocumentSummaryStep` executes, **Then** no stale summary cleanup is performed (no orphan IDs added for summaries).
4. **Given** a document is below the threshold but is not in `changed_document_ids`, **When** `DocumentSummaryStep` executes, **Then** its summary is not marked as orphan (unchanged documents have consistent summary state).

---

### User Story 2 -- Empty Corpus BoK Summary Cleanup (Priority: P2)

As a platform operator, I want the body-of-knowledge summary to be automatically cleaned up when all documents are removed from a source, so that stale BoK entries do not persist in the knowledge store after the entire corpus becomes empty.

**Why this priority**: This is a less frequent edge case (entire corpus removal) but still important for data hygiene. A stale BoK summary in an empty collection could mislead retrieval for other content.

**Independent Test**: Ingest a space with several documents (generating a BoK summary). Remove all documents from the space and re-ingest. Verify the BoK summary entry is deleted from the knowledge store.

**Acceptance Scenarios**:

1. **Given** `seen_doc_ids` is empty (no content chunks) and `removed_document_ids` is non-empty, **When** `BodyOfKnowledgeSummaryStep` executes, **Then** `"body-of-knowledge-summary-0"` is added to `context.orphan_ids` for cleanup.
2. **Given** `seen_doc_ids` is non-empty (content chunks exist), **When** `BodyOfKnowledgeSummaryStep` executes, **Then** BoK summary generation proceeds normally and no orphan ID is added.
3. **Given** `seen_doc_ids` is empty and `removed_document_ids` is also empty (no removals), **When** `BodyOfKnowledgeSummaryStep` executes, **Then** no orphan marking occurs (the step returns early as before).

---

### Edge Cases

- When change detection did not run, `changed_document_ids` and `removed_document_ids` are empty by default. No stale cleanup fires, preserving existing behavior.
- When a document is unchanged but happens to be below the threshold, no cleanup occurs because the summary state is already consistent from a prior ingestion.
- Only summary chunk index 0 is cleaned up (`-summary-0` pattern). The current `DocumentSummaryStep` always produces exactly one summary chunk per document with `chunk_index=0`.
- The `OrphanCleanupStep` deletion logic is unchanged; it already handles all IDs in `context.orphan_ids`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST add `f"{doc_id}-summary-0"` to `context.orphan_ids` when a changed document's chunk count drops below `chunk_threshold` during `DocumentSummaryStep` execution.
- **FR-002**: System MUST only perform stale summary cleanup when `context.change_detection_ran` is True.
- **FR-003**: System MUST only target documents present in `context.changed_document_ids` for stale summary cleanup.
- **FR-004**: System MUST add `"body-of-knowledge-summary-0"` to `context.orphan_ids` when the corpus is empty (`seen_doc_ids` is empty) and `context.removed_document_ids` is non-empty.
- **FR-005**: System MUST preserve existing summarization behavior for documents that still qualify (above threshold).
- **FR-006**: System MUST preserve existing BoK summary generation for non-empty corpora.
- **FR-007**: System MUST log stale summary and BoK cleanup actions at INFO level.

### Key Entities

- **PipelineContext.orphan_ids**: Existing `set[str]` field used by `OrphanCleanupStep` to delete entries from the knowledge store. Two new producers of orphan IDs are added (DocumentSummaryStep and BodyOfKnowledgeSummaryStep).
- **Summary storage ID pattern**: `{doc_id}-summary-0` for per-document summaries, `body-of-knowledge-summary-0` for the BoK summary.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After re-ingestion of a document that dropped below the summary threshold, the old summary entry no longer exists in the knowledge store.
- **SC-002**: After re-ingestion of an empty corpus (all documents removed), the BoK summary entry no longer exists in the knowledge store.
- **SC-003**: Existing summarization behavior for qualifying documents is unaffected (no regressions in existing tests).
- **SC-004**: All new edge-case behaviors are covered by unit tests with meaningful assertions.

## Assumptions

- The `OrphanCleanupStep` already correctly deletes all IDs present in `context.orphan_ids`. No changes to the cleanup step are needed.
- The summary storage ID pattern `{doc_id}-summary-0` is stable and matches the pattern used by `StoreStep`.
- Only index 0 exists for summary chunks (no multi-chunk summary support).
- `removed_document_ids` is populated solely by `ChangeDetectionStep`, so an empty set implicitly means change detection did not run or no removals occurred.

## Clarifications

### Q1: Should stale summary cleanup apply to changed documents only, or also unchanged ones below threshold?

**Answer**: Only changed documents. Unchanged documents have consistent summary state from prior ingestion.

### Q2: Should stale summary cleanup fire when change detection did not run?

**Answer**: No. Without change detection, there is no `changed_document_ids` set to reference.

### Q3: Should we clean up all possible summary chunk indices or only index 0?

**Answer**: Only index 0. The current implementation always produces exactly one summary chunk per document with `chunk_index=0`.

### Q4: Should BoK cleanup check empty-corpus before or after the existing early-return guard?

**Answer**: After. The existing guard handles the "nothing happened" case. The empty-corpus case requires `removed_document_ids` to be non-empty, which passes the guard.

### Q5: Should BoK cleanup handle the case where change detection did not run?

**Answer**: No. If change detection did not run, `removed_document_ids` is empty by default, so the condition is implicitly guarded.
