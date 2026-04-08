# Plan: Summary Lifecycle Management -- Clean Up Stale Summaries and BoK on Edge Cases

**Story:** #36
**Spec:** spec.md
**Date:** 2026-04-08

## Architecture

This change is entirely within the pipeline step layer (`core/domain/pipeline/steps.py`). No new modules, ports, adapters, or external dependencies are introduced. The fix adds orphan-tagging logic to two existing pipeline steps so that the existing `OrphanCleanupStep` handles the deletion.

### Pipeline Flow (Relevant Steps)

```
ChunkStep -> ContentHashStep -> ChangeDetectionStep -> DocumentSummaryStep* -> BodyOfKnowledgeSummaryStep* -> EmbedStep -> StoreStep -> OrphanCleanupStep
```

(*) = modified steps

The key insight is that `OrphanCleanupStep` already deletes any IDs in `context.orphan_ids`. The fix simply ensures the two edge-case IDs are added to that set by the summary steps, which run before `OrphanCleanupStep` in the pipeline.

## Affected Modules

| Module | Change |
|--------|--------|
| `core/domain/pipeline/steps.py` :: `DocumentSummaryStep.execute()` | Add stale per-document summary detection after computing `docs_to_summarize` |
| `core/domain/pipeline/steps.py` :: `BodyOfKnowledgeSummaryStep.execute()` | Add empty-corpus BoK cleanup before the `not seen_doc_ids` early return |
| `tests/core/domain/test_pipeline_steps.py` | Add tests for both edge cases and no-op paths |

## Data Model Deltas

None. No schema changes. The `PipelineContext.orphan_ids` set is already the correct mechanism for tagging entries to delete.

## Interface Contracts

No changes to any port, adapter, or plugin interface.

## Detailed Design

### Change 1: DocumentSummaryStep -- Stale Summary Cleanup

**Location:** `DocumentSummaryStep.execute()`, after the `docs_to_summarize` list comprehension (line ~279).

**Logic:** Iterate over `chunks_by_doc`. For each `doc_id` that is in `context.changed_document_ids` AND has `len(doc_chunks) < self._chunk_threshold`, add `f"{doc_id}-summary-0"` to `context.orphan_ids`. Log the action.

**Why after `docs_to_summarize`?** The `chunks_by_doc` dict and `changed_document_ids` are both available at this point. The stale detection is logically the complement of the summarization filter.

### Change 2: BodyOfKnowledgeSummaryStep -- Empty Corpus Cleanup

**Location:** `BodyOfKnowledgeSummaryStep.execute()`, after computing `seen_doc_ids` but before the `if not seen_doc_ids: return` guard.

**Logic:** If `not seen_doc_ids` AND `context.removed_document_ids` is non-empty, add `"body-of-knowledge-summary-0"` to `context.orphan_ids` and return. Log the action.

**Why before the early return?** The current early return at `if not seen_doc_ids: return` would skip any cleanup logic. By placing the check first, we ensure the orphan ID is tagged before returning.

## Test Strategy

| Test | AC | Description |
|------|----|-------------|
| `test_stale_summary_added_to_orphans_when_below_threshold` | AC-1 | Changed document with < threshold chunks: verify `{doc_id}-summary-0` is in `context.orphan_ids` |
| `test_no_stale_summary_for_unchanged_document_below_threshold` | AC-3 | Unchanged document with < threshold chunks: verify no orphan ID added |
| `test_no_stale_summary_for_changed_document_above_threshold` | AC-3 | Changed document with >= threshold chunks: verify no orphan ID added (gets re-summarized) |
| `test_bok_orphan_on_empty_corpus` | AC-2 | All docs removed, empty chunks: verify `body-of-knowledge-summary-0` in `context.orphan_ids` |
| `test_bok_no_orphan_when_docs_remain` | AC-3 | Some docs remain after removal: verify BoK orphan NOT added |
| `test_bok_no_orphan_when_no_removals` | AC-3 | Normal ingest (no removals): verify BoK orphan NOT added |

All tests use the existing `MockLLMPort` and `MockKnowledgeStorePort` fixtures.

## Rollout Notes

- No configuration changes required.
- No migration needed -- orphan summaries from prior runs will not be retroactively cleaned up. They will be cleaned on the next ingest cycle that triggers change detection for the affected document/corpus.
- Zero risk to existing functionality: the changes only ADD items to `orphan_ids` under specific conditions that previously resulted in no action.
