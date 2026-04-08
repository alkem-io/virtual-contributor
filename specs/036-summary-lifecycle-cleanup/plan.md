# Plan: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Date:** 2026-04-08

## Architecture

No new modules, classes, or architectural changes. This is a surgical bug fix within two existing pipeline step classes.

## Affected Modules

### `core/domain/pipeline/steps.py`

#### 1. `DocumentSummaryStep.execute()` (lines 265-313)

**Change:** After building `docs_to_summarize`, iterate over all documents grouped by `chunks_by_doc`. For any document that:
- Has change detection enabled (`context.change_detection_ran`)
- Is in `context.changed_document_ids`
- Has fewer than `self._chunk_threshold` chunks

Add `f"{doc_id}-summary-0"` to `context.orphan_ids`.

**Integration point:** `context.orphan_ids` is consumed by `OrphanCleanupStep` downstream. No changes needed there.

#### 2. `BodyOfKnowledgeSummaryStep.execute()` (lines 338-399)

**Change:** After computing `seen_doc_ids` (line 348-352), before the `if not seen_doc_ids: return` guard (line 354), add a check: if `seen_doc_ids` is empty and `context.removed_document_ids` is non-empty, add `"body-of-knowledge-summary-0"` to `context.orphan_ids`, then return.

**Integration point:** Same as above -- `OrphanCleanupStep` handles deletion.

## Data Model Deltas

None. `PipelineContext.orphan_ids` already exists as `set[str]`.

## Interface Contracts

No interface changes. Both steps continue to implement the `PipelineStep` protocol.

## Test Strategy

### New Tests (in `tests/core/domain/test_pipeline_steps.py`)

1. **`TestDocumentSummaryStepDedup.test_stale_summary_cleanup_on_threshold_drop`**
   - Setup: Create a context with change detection enabled, doc-1 in `changed_document_ids`, and only 2 content chunks for doc-1.
   - Assert: `"doc-1-summary-0"` in `context.orphan_ids`.

2. **`TestDocumentSummaryStepDedup.test_no_stale_cleanup_when_above_threshold`**
   - Setup: Same as above but with 5 chunks (above threshold).
   - Assert: `"doc-1-summary-0"` not in `context.orphan_ids` (it gets summarized instead).

3. **`TestDocumentSummaryStepDedup.test_no_stale_cleanup_without_change_detection`**
   - Setup: `change_detection_ran=False`, doc with 2 chunks.
   - Assert: `orphan_ids` is empty (no cleanup without change detection).

4. **`TestDocumentSummaryStepDedup.test_no_stale_cleanup_for_unchanged_doc`**
   - Setup: `change_detection_ran=True`, doc-1 NOT in `changed_document_ids`, 2 chunks.
   - Assert: `orphan_ids` is empty (unchanged docs are not touched).

5. **`TestBoKSummaryStepDedup.test_bok_cleanup_on_empty_corpus`**
   - Setup: `change_detection_ran=True`, `removed_document_ids={"doc-1"}`, no content chunks.
   - Assert: `"body-of-knowledge-summary-0"` in `context.orphan_ids`.

6. **`TestBoKSummaryStepDedup.test_no_bok_cleanup_when_docs_remain`**
   - Setup: `change_detection_ran=True`, `removed_document_ids={"doc-2"}`, content chunks for doc-1 present.
   - Assert: `"body-of-knowledge-summary-0"` not in `context.orphan_ids`.

### Existing Tests

All existing tests must continue to pass. The new code paths are guarded by conditions (`change_detection_ran`, `changed_document_ids`, `removed_document_ids`) that existing tests do not trigger.

## Rollout Notes

- Zero-risk deployment -- the fix only adds IDs to an existing set that is already consumed by `OrphanCleanupStep`.
- No configuration changes needed.
- No migration needed -- stale entries will be cleaned up on the next ingest cycle for affected collections.
