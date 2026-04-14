# Tasks: Story #36 -- Summary Lifecycle Management

**Date:** 2026-04-14

## Task List (dependency-ordered)

### T1: Add stale per-document summary cleanup to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Dependencies:** None
**Description:** After building `docs_to_summarize` in `DocumentSummaryStep.execute()`, iterate over `chunks_by_doc` to find changed documents that now fall below `chunk_threshold`. For each, add `f"{doc_id}-summary-0"` to `context.orphan_ids` and log the action.

**Acceptance Criteria:**
- When `change_detection_ran` is True and a doc_id is in `changed_document_ids` and has fewer chunks than `chunk_threshold`, `f"{doc_id}-summary-0"` is added to `context.orphan_ids`.
- When `change_detection_ran` is False, no orphan marking occurs.
- When a doc is changed but still above threshold, no orphan marking occurs.
- No changes to summarization logic for qualifying documents.

**Tests:** T4.1, T4.2, T4.3

### T2: Add empty-corpus BoK summary cleanup to BodyOfKnowledgeSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Dependencies:** None
**Description:** In `BodyOfKnowledgeSummaryStep.execute()`, replace the bare `if not seen_doc_ids: return` with logic that checks `context.removed_document_ids`. If removals exist and corpus is empty, add `"body-of-knowledge-summary-0"` to `context.orphan_ids` before returning.

**Acceptance Criteria:**
- When `seen_doc_ids` is empty and `removed_document_ids` is non-empty, `"body-of-knowledge-summary-0"` is added to `context.orphan_ids`.
- When `seen_doc_ids` is empty and `removed_document_ids` is empty, no orphan marking occurs (just returns as before).
- When `seen_doc_ids` is non-empty, BoK summary generation proceeds normally.

**Tests:** T4.4, T4.5

### T3: Write unit tests for stale per-document summary cleanup (T1)

**File:** `tests/core/domain/test_pipeline_steps.py`
**Dependencies:** T1
**Description:** Add tests to `TestDocumentSummaryStep`:

- **T4.1 `test_stale_summary_marked_as_orphan`**: Set up context with change_detection_ran=True, a doc_id in changed_document_ids, and fewer chunks than threshold. Assert `f"{doc_id}-summary-0"` is in `context.orphan_ids`.
- **T4.2 `test_no_orphan_when_still_above_threshold`**: Changed doc with >= threshold chunks. Assert orphan_ids does not contain the summary ID.
- **T4.3 `test_no_stale_cleanup_without_change_detection`**: Set change_detection_ran=False, doc below threshold. Assert orphan_ids is empty.

### T4: Write unit tests for empty-corpus BoK cleanup (T2)

**File:** `tests/core/domain/test_pipeline_steps.py`
**Dependencies:** T2
**Description:** Add tests to `TestBodyOfKnowledgeSummaryStep`:

- **T4.4 `test_bok_summary_orphaned_on_empty_corpus`**: Set up context with no content chunks, non-empty removed_document_ids, change_detection_ran=True. Assert `"body-of-knowledge-summary-0"` is in context.orphan_ids.
- **T4.5 `test_bok_summary_not_orphaned_when_docs_exist`**: Set up context with content chunks present. Assert orphan_ids does not contain BoK summary ID.

### T5: Run full test suite and verify green

**Dependencies:** T1, T2, T3, T4
**Description:** Run `poetry run pytest` and verify all tests pass including new ones. Run lint and typecheck.
