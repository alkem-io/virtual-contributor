# Plan: Handle Empty Corpus Re-Ingestion

**Story:** #35
**Date:** 2026-04-14

## Architecture

This is a targeted bug fix in two plugin modules. No new modules, no new abstractions, no architectural changes. The fix reuses the existing `IngestEngine` + pipeline steps to run a minimal cleanup pipeline when the fetch succeeds but produces zero documents.

### Approach

In both `IngestSpacePlugin` and `IngestWebsitePlugin`, replace the early `return success` on empty documents with a cleanup pipeline run:

```
[fetch succeeds, 0 documents] --> IngestEngine([ChangeDetectionStep, OrphanCleanupStep]).run([], collection)
```

The `ChangeDetectionStep` will:
1. See zero incoming chunks (no documents = no chunks after ChunkStep, but we skip ChunkStep entirely)
2. Query the store for all existing document IDs in the collection
3. Mark ALL existing document IDs as `removed_document_ids` (since `current_doc_ids` is empty)

The `OrphanCleanupStep` will:
1. Delete all chunks for each removed document (content + summary)

This is the minimal correct pipeline. We do NOT need `ChunkStep`, `ContentHashStep`, `EmbedStep`, `StoreStep`, `DocumentSummaryStep`, or `BodyOfKnowledgeSummaryStep` because there are no documents to process.

## Affected Modules

| Module | Change |
|--------|--------|
| `plugins/ingest_space/plugin.py` | Replace early return on `not documents` with cleanup pipeline run |
| `plugins/ingest_website/plugin.py` | Replace early return on `not documents` with cleanup pipeline run |
| `tests/plugins/test_ingest_space.py` | Add tests for empty-but-successful and failure scenarios |
| `tests/plugins/test_ingest_website.py` | Add tests for empty-but-successful and failure scenarios |

## Data Model Deltas

None. No changes to `Document`, `Chunk`, `DocumentMetadata`, `IngestResult`, `PipelineContext`, or any event model.

## Interface Contracts

No changes to any port, protocol, or public API. The plugin `handle()` method signatures remain identical. The return types remain identical.

## Test Strategy

### Unit Tests

1. **IngestSpacePlugin -- empty space cleanup:** Mock `read_space_tree` to return `[]`. Pre-populate the mock knowledge store with existing chunks. Assert that after `handle()`, the cleanup pipeline ran and all pre-existing chunks were deleted.

2. **IngestSpacePlugin -- fetch failure preserved:** Mock `read_space_tree` to raise an exception. Assert `result="failure"` and no cleanup ran.

3. **IngestWebsitePlugin -- empty crawl cleanup:** Mock `crawl` to return `[]`. Pre-populate the mock knowledge store with existing chunks. Assert that after `handle()`, the cleanup pipeline ran and all pre-existing chunks were deleted.

4. **IngestWebsitePlugin -- crawl with no extractable text cleanup:** Mock `crawl` to return pages with empty text. Assert cleanup pipeline runs.

5. **IngestWebsitePlugin -- crawl failure preserved:** Mock `crawl` to raise an exception. Assert `result="failure"` and no cleanup ran.

6. **Existing test preservation:** All existing tests must continue to pass with zero changes.

### Integration Tests

Not applicable -- the pipeline engine and steps have their own comprehensive unit tests. The plugins are tested with mock ports.

## Rollout Notes

- Zero-risk change. The affected code path (empty documents) previously returned early with no side effects. Now it will actively clean up stale data.
- No configuration changes.
- No new environment variables.
- No migration needed.
- Backward compatible: the only observable change is that stale chunks get deleted when they should have been deleted before.
