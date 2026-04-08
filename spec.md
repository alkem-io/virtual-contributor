# Spec: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** alkem-io/virtual-contributor#36
**Epic:** alkem-io/alkemio#1820
**Date:** 2026-04-08

## User Value

Prevent orphaned summary entries from accumulating in the knowledge store, which could degrade RAG retrieval quality by surfacing stale or phantom summaries that no longer correspond to current documents.

## Scope

1. **Stale per-document summary cleanup**: When a document drops below the summary threshold (currently 4 chunks) after re-chunking, the existing `{doc_id}-summary-0` entry must be added to `context.orphan_ids` so `OrphanCleanupStep` deletes it.
2. **Empty corpus BoK cleanup**: When all documents are removed from the source (seen_doc_ids is empty and removed_document_ids is non-empty), `body-of-knowledge-summary-0` must be added to `context.orphan_ids` so `OrphanCleanupStep` deletes it.

## Out of Scope

- Changes to the summary threshold value itself.
- Changes to `OrphanCleanupStep` logic (it already handles `orphan_ids` correctly).
- Changes to `ChangeDetectionStep` logic.
- Changes to the `StoreStep` or `EmbedStep`.
- Multi-chunk summary entries (the system currently only produces index-0 summaries).

## Acceptance Criteria

1. **AC-1**: Given a document that previously had >3 chunks (triggering summary generation) and after re-ingest has <=3 chunks, when `DocumentSummaryStep.execute()` runs, then `f"{doc_id}-summary-0"` is added to `context.orphan_ids`.
2. **AC-2**: Given that ALL documents have been removed from the source, when `BodyOfKnowledgeSummaryStep.execute()` runs, then `"body-of-knowledge-summary-0"` is added to `context.orphan_ids`.
3. **AC-3**: Both cleanup paths are covered by unit tests that verify orphan IDs are correctly populated.
4. **AC-4**: Existing tests continue to pass (no regressions).

## Constraints

- Only `core/domain/pipeline/steps.py` should be modified for production code.
- Tests go in `tests/core/domain/test_pipeline_steps.py`.
- No new dependencies required.
- The fix must not alter behavior when documents are above threshold or when the corpus is non-empty.
