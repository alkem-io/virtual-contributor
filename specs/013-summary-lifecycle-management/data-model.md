# Data Model: Summary Lifecycle Management

**Feature Branch**: `story/36-summary-lifecycle-cleanup`
**Date**: 2026-04-14

## Overview

This feature does not introduce any new entities, fields, or schema changes. It leverages the existing `PipelineContext.orphan_ids` mechanism to mark stale summaries for cleanup. All changes are behavioral additions within existing pipeline steps.

## Entity: PipelineContext (unchanged)

**File**: `core/domain/ingest_pipeline.py`

### Relevant Existing Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `orphan_ids` | `set[str]` | `set()` | IDs of entries to be deleted by `OrphanCleanupStep` |
| `change_detection_ran` | `bool` | `False` | Whether `ChangeDetectionStep` executed |
| `changed_document_ids` | `set[str]` | `set()` | Document IDs modified since last ingestion |
| `removed_document_ids` | `set[str]` | `set()` | Document IDs removed since last ingestion |

### New Orphan ID Producers

Two existing pipeline steps now produce orphan IDs in addition to the existing producer (`ChangeDetectionStep`):

| Producer | Condition | Orphan ID Added |
|----------|-----------|-----------------|
| `ChangeDetectionStep` (existing) | Document removed between ingestions | `{doc_id}-{chunk_index}` for each chunk |
| `DocumentSummaryStep` (new) | Changed doc drops below `chunk_threshold` | `{doc_id}-summary-0` |
| `BodyOfKnowledgeSummaryStep` (new) | Empty corpus with removals | `body-of-knowledge-summary-0` |

## Entity: DocumentSummaryStep (behavioral change)

**File**: `core/domain/pipeline/steps.py`

### Changed Behavior

- **Before**: Only produced summary chunks for qualifying documents (>= threshold chunks). Did not interact with `orphan_ids`.
- **After**: Additionally marks stale summaries as orphans when a changed document drops below the threshold.

No new fields or constructor parameters.

## Entity: BodyOfKnowledgeSummaryStep (behavioral change)

**File**: `core/domain/pipeline/steps.py`

### Changed Behavior

- **Before**: Returned early with no action when `seen_doc_ids` was empty.
- **After**: When `seen_doc_ids` is empty AND `removed_document_ids` is non-empty, adds `"body-of-knowledge-summary-0"` to `orphan_ids` before returning.

No new fields or constructor parameters.

## Relationships

```text
PipelineContext.orphan_ids
  ├── populated by → ChangeDetectionStep (existing: removed document chunks)
  ├── populated by → DocumentSummaryStep (NEW: stale per-document summaries)
  ├── populated by → BodyOfKnowledgeSummaryStep (NEW: empty-corpus BoK summary)
  └── consumed by → OrphanCleanupStep (existing: deletes all orphan IDs from store)
```

## State Transitions

No state machines affected. The `orphan_ids` set is populated during pipeline execution and consumed at the end by `OrphanCleanupStep`. The new producers add IDs to the same set using the same pattern.
