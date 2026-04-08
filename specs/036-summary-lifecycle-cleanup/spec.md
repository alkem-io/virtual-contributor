# Spec: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

When documents shrink below the summarization threshold or the entire corpus is emptied, stale summary entries persist in the knowledge store. These orphaned entries degrade retrieval quality by returning outdated context to users. Cleaning them up ensures the knowledge base remains accurate and free of stale data.

## Scope

### In Scope

1. **Stale per-document summary cleanup:** When a changed document drops to fewer chunks than the summary threshold (currently `chunk_threshold`, default 4), the existing `{doc_id}-summary-0` entry must be added to `context.orphan_ids` so `OrphanCleanupStep` deletes it.

2. **Empty corpus BoK cleanup:** When `BodyOfKnowledgeSummaryStep` detects that all documents have been removed (i.e., `seen_doc_ids` is empty and `removed_document_ids` is non-empty), it must add `"body-of-knowledge-summary-0"` to `context.orphan_ids`.

### Out of Scope

- Changes to `ChangeDetectionStep` logic itself.
- Changes to `OrphanCleanupStep` logic -- it already handles `context.orphan_ids` and `context.removed_document_ids` correctly.
- Changes to the `StoreStep` ID scheme.
- Multi-chunk summary support (summaries always have `chunk_index=0`).
- Cleanup of BoK summaries in non-empty-corpus scenarios (the BoK is regenerated when any document changes).

## Acceptance Criteria

1. **AC1:** When a previously summarized document (with >threshold chunks on last ingest) is re-ingested with <=threshold chunks, the `{doc_id}-summary-0` storage ID is added to `context.orphan_ids` during `DocumentSummaryStep.execute()`.

2. **AC2:** When the entire corpus becomes empty (all documents removed, no content chunks remain), `body-of-knowledge-summary-0` is added to `context.orphan_ids` during `BodyOfKnowledgeSummaryStep.execute()`.

3. **AC3:** Both cleanup paths are covered by unit tests that verify the correct IDs appear in `context.orphan_ids`.

4. **AC4:** All existing tests continue to pass without modification.

5. **AC5:** No changes outside `core/domain/pipeline/steps.py` and test files.

## Constraints

- The fix must be minimal and surgical -- only `DocumentSummaryStep.execute()` and `BodyOfKnowledgeSummaryStep.execute()` are modified.
- The summary storage ID format is `{doc_id}-summary-{chunk_index}`, and `chunk_index` is always 0 for document summaries.
- The BoK storage ID format is `body-of-knowledge-summary-0`.
- `context.orphan_ids` is a `set[str]` that `OrphanCleanupStep` already consumes; adding IDs to it is the correct integration point.
- `change_detection_ran` and `changed_document_ids` must be respected to avoid false positives on fresh ingests without change detection.
