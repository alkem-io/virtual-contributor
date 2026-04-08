# Plan: Handle Empty Corpus Re-ingestion

**Story**: alkem-io/virtual-contributor#35
**Spec**: spec.md
**Date**: 2026-04-08

## Architecture

No new modules, adapters, or ports are introduced. The change is localized to two plugin files, replacing their early-return-on-empty paths with a cleanup-only pipeline invocation.

### Affected Modules

| Module | Change |
|--------|--------|
| `plugins/ingest_space/plugin.py` | Replace empty-document early-return with cleanup-only pipeline (ChangeDetectionStep + OrphanCleanupStep) |
| `plugins/ingest_website/plugin.py` | Same treatment for the post-crawl empty-document path |
| `tests/plugins/test_ingest_space.py` | Add tests for empty-corpus cleanup behavior |
| `tests/plugins/test_ingest_website.py` | Add tests for empty-corpus cleanup behavior |

### Data Model Deltas

None. The `PipelineContext`, `IngestResult`, `Document`, `Chunk`, and event models are unchanged.

### Interface Contracts

No changes to any port protocol or plugin contract. The `IngestEngine.run()` signature is unchanged -- it already accepts an empty document list.

## Design

### Cleanup-Only Pipeline Pattern

When a fetch succeeds but returns zero documents, both plugins will construct and run a minimal pipeline consisting of only:

1. `ChangeDetectionStep(knowledge_store_port=self._knowledge_store)`
2. `OrphanCleanupStep(knowledge_store_port=self._knowledge_store)`

This pipeline receives an empty `documents` list. The `ChangeDetectionStep._detect()` method will:
- Find `current_doc_ids = {}` (empty, since no chunks exist)
- Fetch all `existing_doc_ids` from the store
- Compute `removed_document_ids = existing_doc_ids - current_doc_ids = existing_doc_ids` (all existing docs are "removed")

The `OrphanCleanupStep.execute()` will then delete all chunks for each removed document ID.

### Error Handling

- Fetch failure (exception in `read_space_tree()` or `crawl()`): preserved as-is, caught by the outer `except` block, returns failure result.
- Cleanup pipeline failure: any errors from `ChangeDetectionStep` or `OrphanCleanupStep` are captured in `IngestResult.errors`. The plugin returns success/failure based on the result.

### Result Messages

- IngestSpacePlugin: Returns `result="success"` after cleanup, consistent with existing behavior.
- IngestWebsitePlugin: Returns `result=IngestionResult.SUCCESS` with empty error string (not `"No content extracted"` -- the cleanup is useful work, not an error).

### Logging

Both plugins log at INFO level when entering the cleanup-only path, e.g.:
```
"Source returned zero documents for collection %s; running cleanup pipeline"
```

## Test Strategy

### Unit Tests (new)

1. **test_empty_corpus_cleanup_deletes_existing_chunks** (ingest_space): Seed MockKnowledgeStorePort with pre-existing chunks. Mock `read_space_tree` to return empty list. Verify chunks are deleted after handle().
2. **test_empty_corpus_cleanup_deletes_existing_chunks** (ingest_website): Same pattern with mocked crawl returning pages but no extractable text.
3. **test_crawl_failure_preserves_existing_chunks** (ingest_website): Mock crawl to raise exception. Verify chunks are NOT deleted.

### Existing Tests

All existing tests must continue to pass unchanged. The normal (non-empty) ingestion path is not modified.

## Rollout Notes

- No configuration changes required.
- No database migrations.
- Backward compatible -- existing behavior for non-empty ingestion is preserved.
- The change is safe to deploy incrementally since it only affects the empty-document code path that previously did nothing useful.
