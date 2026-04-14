# Spec: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Date:** 2026-04-14

## User Value

Prevent orphaned summary entries from accumulating in the knowledge store after re-ingestion. Stale summaries can mislead RAG retrieval by surfacing outdated content that no longer reflects the current corpus, degrading answer quality.

## Scope

1. **Stale per-document summary cleanup:** When a previously summarized document (>3 chunks) is re-ingested and now has <=3 chunks, the old `{doc_id}-summary-0` entry must be added to `context.orphan_ids` so `OrphanCleanupStep` removes it.
2. **Empty corpus BoK cleanup:** When all documents are removed from the source (empty corpus), the `body-of-knowledge-summary-0` entry must be added to `context.orphan_ids` so `OrphanCleanupStep` removes it.

## Out of Scope

- Changes to the `OrphanCleanupStep` deletion logic itself (it already handles `context.orphan_ids`).
- Changes to the chunk threshold configuration mechanism.
- Changes to the `ChangeDetectionStep` logic.
- Multi-summary chunks (only `-summary-0` pattern exists today).
- UI/API changes.

## Acceptance Criteria

1. **AC-1:** When change detection has run and a changed document now has fewer chunks than `chunk_threshold`, `DocumentSummaryStep` adds `f"{doc_id}-summary-0"` to `context.orphan_ids`.
2. **AC-2:** When `seen_doc_ids` is empty (no content chunks) and `removed_document_ids` is non-empty, `BodyOfKnowledgeSummaryStep` adds `"body-of-knowledge-summary-0"` to `context.orphan_ids`.
3. **AC-3:** Existing behavior is preserved -- documents that still qualify for summarization continue to be summarized normally.
4. **AC-4:** Existing behavior is preserved -- BoK summary generation still works when the corpus is non-empty.
5. **AC-5:** All new behavior is covered by unit tests.

## Constraints

- Changes are limited to `core/domain/pipeline/steps.py`.
- Must not break any existing tests.
- Must follow the existing step contract pattern (duck-typed `PipelineStep` protocol).
