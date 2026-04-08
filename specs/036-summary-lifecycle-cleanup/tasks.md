# Tasks: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Date:** 2026-04-08

## Task List

### T1: Add stale per-document summary cleanup to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**Description:** In `DocumentSummaryStep.execute()`, after building `docs_to_summarize`, detect changed documents that now fall below `self._chunk_threshold` and add their summary storage IDs to `context.orphan_ids`.

**Implementation:**
- After `docs_to_summarize` is computed (line 279), iterate over `chunks_by_doc`.
- For each `doc_id` where:
  - `context.change_detection_ran` is True
  - `doc_id in context.changed_document_ids`
  - `len(doc_chunks) < self._chunk_threshold`
- Add `f"{doc_id}-summary-0"` to `context.orphan_ids`.
- Log at INFO level.

**Acceptance criteria:**
- When a changed document drops below chunk threshold, its summary ID appears in `context.orphan_ids`.
- When a changed document is at or above threshold, it is summarized normally (no orphan ID added).
- When change detection has not run, no stale cleanup occurs.
- When a document is not in `changed_document_ids`, no stale cleanup occurs.

**Tests:** T3 (tests 1-4)

---

### T2: Add empty corpus BoK cleanup to BodyOfKnowledgeSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**Description:** In `BodyOfKnowledgeSummaryStep.execute()`, when no content chunks remain and documents have been removed, add the BoK summary storage ID to `context.orphan_ids`.

**Implementation:**
- After computing `seen_doc_ids` (line 352), before the `if not seen_doc_ids: return` guard (line 354):
  - If `not seen_doc_ids` and `context.removed_document_ids`:
    - Add `"body-of-knowledge-summary-0"` to `context.orphan_ids`
    - Log at INFO level
    - Return

**Acceptance criteria:**
- When corpus is empty and documents were removed, `"body-of-knowledge-summary-0"` appears in `context.orphan_ids`.
- When corpus still has documents, the BoK summary is regenerated normally (no orphan ID added).
- No BoK summary chunk is generated for an empty corpus.

**Tests:** T3 (tests 5-6)

---

### T3: Write unit tests for both cleanup paths

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1, T2
**Description:** Add test cases to the existing test classes to verify both stale summary and empty corpus BoK cleanup behaviors.

**Tests to add:**

1. `TestDocumentSummaryStepDedup.test_stale_summary_cleanup_on_threshold_drop`
2. `TestDocumentSummaryStepDedup.test_no_stale_cleanup_when_above_threshold`
3. `TestDocumentSummaryStepDedup.test_no_stale_cleanup_without_change_detection`
4. `TestDocumentSummaryStepDedup.test_no_stale_cleanup_for_unchanged_doc`
5. `TestBoKSummaryStepDedup.test_bok_cleanup_on_empty_corpus`
6. `TestBoKSummaryStepDedup.test_no_bok_cleanup_when_docs_remain`

**Acceptance criteria:**
- All 6 new tests pass.
- All existing tests continue to pass.
- Tests cover both positive (cleanup triggered) and negative (cleanup not triggered) cases.

---

### T4: Run full test suite and static analysis

**Depends on:** T1, T2, T3
**Description:** Verify all exit gates pass.

**Acceptance criteria:**
- `poetry run pytest` passes with zero failures.
- `poetry run ruff check core/ plugins/ tests/` passes.
- `poetry run pyright core/ plugins/` passes.
