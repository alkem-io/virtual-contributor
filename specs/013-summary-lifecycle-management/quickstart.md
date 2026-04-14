# Quickstart: Summary Lifecycle Management

**Feature Branch**: `story/36-summary-lifecycle-cleanup`
**Date**: 2026-04-14

## What This Feature Does

Fixes two edge cases where stale summary entries persist in the knowledge store after re-ingestion:

1. **Stale per-document summary cleanup** -- When a previously summarized document is re-ingested with reduced content (dropping below the chunk threshold), the old summary entry is automatically marked for deletion.
2. **Empty corpus BoK summary cleanup** -- When all documents are removed from a source (empty corpus), the body-of-knowledge summary entry is automatically marked for deletion.

Both fixes use the existing `OrphanCleanupStep` mechanism. No new configuration or environment variables are needed.

## Quick Verification

### 1. Stale per-document summary cleanup

```bash
# Run the unit tests for stale summary cleanup
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestDocumentSummaryStepStaleCleanup -v

# Expected: 4 tests pass
# - test_stale_summary_marked_as_orphan
# - test_no_orphan_when_still_above_threshold
# - test_no_stale_cleanup_without_change_detection
# - test_stale_cleanup_only_targets_changed_docs
```

### 2. Empty corpus BoK summary cleanup

```bash
# Run the unit tests for BoK summary cleanup
poetry run pytest tests/core/domain/test_pipeline_steps.py::TestBoKSummaryStepEmptyCorpusCleanup -v

# Expected: 3 tests pass
# - test_bok_summary_orphaned_on_empty_corpus
# - test_bok_summary_not_orphaned_when_docs_exist
# - test_bok_not_orphaned_on_empty_corpus_without_removals
```

### 3. Full test suite

```bash
# Verify no regressions
poetry run pytest

# All existing tests must continue to pass
```

## Files Changed

| File | Change |
|------|--------|
| `core/domain/pipeline/steps.py` | Add stale-summary detection loop in `DocumentSummaryStep.execute()` (~17 lines); add empty-corpus orphan marking in `BodyOfKnowledgeSummaryStep.execute()` (~7 lines) |
| `tests/core/domain/test_pipeline_steps.py` | Add `TestDocumentSummaryStepStaleCleanup` (4 tests) and `TestBoKSummaryStepEmptyCorpusCleanup` (3 tests) |

## Contracts

No external interface changes:
- **PipelineStep protocol**: Unchanged (steps still implement `execute(context)`)
- **PipelineContext**: Unchanged (existing `orphan_ids` field used as-is)
- **OrphanCleanupStep**: Unchanged (already handles all IDs in `orphan_ids`)
- **PluginContract**: Unchanged
- **Event schemas**: Unchanged
