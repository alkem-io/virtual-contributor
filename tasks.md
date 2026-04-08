# Tasks: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** alkem-io/virtual-contributor#36
**Date:** 2026-04-08

## Task List

### T1: Add stale per-document summary cleanup to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**AC:** After `DocumentSummaryStep.execute()` runs, any document in `changed_document_ids` with fewer than `chunk_threshold` chunks has `f"{doc_id}-summary-0"` added to `context.orphan_ids`.
**Tests:**
- `test_stale_summary_added_to_orphans`: Changed doc with <=3 chunks => summary ID in orphan_ids
- `test_no_stale_summary_for_unchanged_doc`: Unchanged doc below threshold => no orphan
- `test_no_stale_summary_when_above_threshold`: Changed doc above threshold => no orphan
- `test_no_stale_summary_without_change_detection`: change_detection_ran is False => no orphan cleanup logic fires

### T2: Add empty corpus BoK cleanup to BodyOfKnowledgeSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**AC:** When `seen_doc_ids` is empty and `removed_document_ids` is non-empty, `"body-of-knowledge-summary-0"` is added to `context.orphan_ids`.
**Tests:**
- `test_empty_corpus_bok_orphaned`: All docs removed => BoK ID in orphan_ids
- `test_non_empty_corpus_bok_not_orphaned`: Some docs remain => BoK ID NOT in orphan_ids

### T3: Write unit tests for T1 and T2

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1, T2
**AC:** All new tests pass. All existing tests continue to pass.

### T4: Run full test suite, lint, and typecheck

**Depends on:** T3
**AC:** `poetry run pytest` passes. `poetry run ruff check core/ plugins/ tests/` passes. `poetry run pyright core/ plugins/` passes (or matches baseline).
