# Tasks: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Plan:** plan.md
**Date:** 2026-04-08

## Task List

### T1: Add stale per-document summary detection to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**AC:** AC-1, AC-3

**Description:** In `DocumentSummaryStep.execute()`, after computing `docs_to_summarize`, iterate over all entries in `chunks_by_doc`. For each `doc_id` where:
- `context.change_detection_ran` is True
- `doc_id` is in `context.changed_document_ids`
- `len(doc_chunks) < self._chunk_threshold`

Add `f"{doc_id}-summary-0"` to `context.orphan_ids` and log at INFO level.

**Acceptance test:** `test_stale_summary_added_to_orphans_when_below_threshold`

---

### T2: Add empty-corpus BoK cleanup to BodyOfKnowledgeSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**AC:** AC-2, AC-3

**Description:** In `BodyOfKnowledgeSummaryStep.execute()`, after computing `seen_doc_ids` and before the `if not seen_doc_ids: return` guard, add a check: if `not seen_doc_ids` and `context.removed_document_ids`, add `"body-of-knowledge-summary-0"` to `context.orphan_ids`, log at INFO, and return early.

**Acceptance test:** `test_bok_orphan_on_empty_corpus`

---

### T3: Write unit tests for stale per-document summary cleanup

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**AC:** AC-1, AC-3, AC-4

**Tests:**
1. `test_stale_summary_added_to_orphans_when_below_threshold` -- Changed doc with < threshold chunks has summary orphan tagged
2. `test_no_stale_summary_for_unchanged_document_below_threshold` -- Unchanged doc below threshold: no orphan tagged
3. `test_no_stale_summary_for_changed_document_above_threshold` -- Changed doc above threshold: no orphan tagged (gets re-summarized instead)

---

### T4: Write unit tests for empty-corpus BoK cleanup

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T2
**AC:** AC-2, AC-3, AC-4

**Tests:**
1. `test_bok_orphan_on_empty_corpus` -- All docs removed, no content chunks: BoK orphan tagged
2. `test_bok_no_orphan_when_docs_remain` -- Some docs remain: BoK orphan NOT tagged
3. `test_bok_no_orphan_when_no_removals` -- No removals: BoK orphan NOT tagged

---

### T5: Run full test suite and verify all gates pass

**Depends on:** T1, T2, T3, T4
**AC:** All

**Description:** Run `poetry run pytest`, `poetry run ruff check core/ plugins/ tests/`, and `poetry run pyright core/ plugins/`. All must pass.

## Dependency Order

```
T1 ──┐
     ├── T3 ──┐
T2 ──┤        ├── T5
     ├── T4 ──┘
     │
```

T1 and T2 are independent and can be done in parallel.
T3 depends on T1. T4 depends on T2.
T5 depends on all prior tasks.
