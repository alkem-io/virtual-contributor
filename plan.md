# Plan: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Date:** 2026-04-14

## Architecture

No architectural changes. This is a localized bug fix within two existing pipeline steps. The orphan-ID mechanism (`context.orphan_ids`) already exists and is consumed by `OrphanCleanupStep`. We are adding two new producers of orphan IDs.

## Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` :: `DocumentSummaryStep.execute()` | Add stale-summary detection loop after computing `docs_to_summarize` |
| `core/domain/pipeline/steps.py` :: `BodyOfKnowledgeSummaryStep.execute()` | Replace bare early-return on empty `seen_doc_ids` with orphan-marking logic |
| `tests/core/domain/test_pipeline_steps.py` | Add 4-5 new test cases |

## Data Model Deltas

None. Existing `PipelineContext.orphan_ids: set[str]` is used as-is.

## Interface Contracts

No changes. `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` continue to conform to `PipelineStep` protocol. `OrphanCleanupStep` already deletes all IDs in `context.orphan_ids`.

## Detailed Changes

### 1. DocumentSummaryStep -- Stale summary detection

In `execute()`, after building `docs_to_summarize`, add a loop:

```
For each (doc_id, doc_chunks) in chunks_by_doc:
    if change_detection_ran
       AND doc_id in changed_document_ids
       AND len(doc_chunks) < chunk_threshold:
        add f"{doc_id}-summary-0" to context.orphan_ids
        log at info level
```

This targets changed documents whose chunk count dropped below the threshold. The orphan ID matches the storage ID pattern used by `StoreStep` for summary chunks.

### 2. BodyOfKnowledgeSummaryStep -- Empty corpus detection

Replace the existing:
```python
if not seen_doc_ids:
    return
```

With:
```python
if not seen_doc_ids:
    if context.removed_document_ids:
        context.orphan_ids.add("body-of-knowledge-summary-0")
        logger.info("Corpus empty after removals; marking BoK summary for cleanup")
    return
```

This marks the BoK summary entry for deletion when the corpus becomes empty due to document removals.

## Test Strategy

| Test | Validates |
|------|-----------|
| `test_stale_summary_marked_as_orphan` | AC-1: Changed doc drops below threshold, summary ID added to orphan_ids |
| `test_no_orphan_when_still_above_threshold` | AC-3: Docs that still qualify are not orphaned |
| `test_no_orphan_when_change_detection_not_ran` | Clarification Q2: No orphan marking without change detection |
| `test_bok_summary_orphaned_on_empty_corpus` | AC-2: Empty corpus with removals marks BoK summary |
| `test_bok_summary_not_orphaned_when_docs_exist` | AC-4: Non-empty corpus does not orphan BoK summary |

## Rollout Notes

- No configuration changes needed.
- No migration needed -- orphaned entries will be cleaned up on next re-ingest.
- Backward compatible: the new behavior only triggers on edge cases that previously left stale data.
