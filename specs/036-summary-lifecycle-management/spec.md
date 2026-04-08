# Spec: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

## User Value

Prevent orphaned summary entries from accumulating in the knowledge store, which can pollute RAG retrieval results with stale or irrelevant summaries. Users receive cleaner, more accurate answers when the knowledge store does not contain ghost summaries from documents that no longer qualify or from entirely emptied corpora.

## Scope

### In Scope

1. **Stale per-document summary cleanup:** When a changed document drops below the summary chunk threshold (currently `chunk_threshold`, default 4), add its `{doc_id}-summary-0` entry to `context.orphan_ids` so `OrphanCleanupStep` deletes it.

2. **Empty corpus BoK cleanup:** When all documents have been removed from the source (i.e., `seen_doc_ids` is empty and `removed_document_ids` is non-empty), add `body-of-knowledge-summary-0` to `context.orphan_ids` so `OrphanCleanupStep` deletes it.

### Out of Scope

- Modifying `OrphanCleanupStep` itself (it already handles `context.orphan_ids`).
- Changing the summary threshold logic or the chunk threshold configuration.
- Addressing partial corpus removal (some documents remain); the BoK summary step already regenerates in that case.
- Any transport, event, or API changes.
- Changes to the store port interface or adapter implementations.

## Acceptance Criteria

1. **AC-1:** When a document previously had >= `chunk_threshold` chunks and after re-chunking has < `chunk_threshold` chunks, and the document is in `changed_document_ids`, the `{doc_id}-summary-0` ID is added to `context.orphan_ids`.

2. **AC-2:** When change detection reports all documents removed (no remaining content chunks) and `removed_document_ids` is non-empty, `body-of-knowledge-summary-0` is added to `context.orphan_ids`.

3. **AC-3:** Normal operation (documents above threshold, partial corpus, no changes) is unaffected -- no false positives on cleanup.

4. **AC-4:** Unit tests cover both edge cases and the no-op paths.

## Constraints

- Changes are limited to `core/domain/pipeline/steps.py`.
- No new dependencies.
- Must not break existing tests.
- The summary storage ID format is `{doc_id}-summary-0` (deterministic, see `StoreStep`).
- The BoK storage ID format is `body-of-knowledge-summary-0`.

## Clarifications

| # | Ambiguity | Decision | Rationale |
|---|-----------|----------|-----------|
| 1 | Should stale summary cleanup apply to all below-threshold documents or only changed ones? | Only documents in `changed_document_ids` | Unchanged documents below threshold never had a summary, or their summary was already cleaned in a prior run. Avoids false positives. |
| 2 | Issue says "<=3 chunks" but code uses configurable `chunk_threshold=4` with `>=` | Use `len(doc_chunks) < self._chunk_threshold` | Makes the cleanup condition consistent with the summarization condition and respects the configurable threshold. |
| 3 | Should the empty-corpus BoK check fire before or after the `not seen_doc_ids` early return? | Before the early return | The early return would skip the cleanup logic; the check must precede it to ensure the orphan ID is added. |
| 4 | Partial removal: should BoK be deleted when some documents remain? | No, only when corpus is fully empty | Partial removal triggers BoK regeneration (existing behavior). Deletion only when zero content documents remain. |

**Clarify loop iterations:** 2 (0 new ambiguities on iteration 2)
