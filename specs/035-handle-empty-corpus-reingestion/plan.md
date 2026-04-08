# Plan: Handle Empty Corpus Re-ingestion

**Story:** #35
**Date:** 2026-04-08

---

## Architecture

No architectural changes. The fix is localized to the two ingest plugins. The pipeline engine, pipeline steps, event models, and ports remain unchanged.

### Affected Modules

| Module | Change Type | Description |
|--------|------------|-------------|
| `plugins/ingest_space/plugin.py` | Modify | Replace early-return on empty docs with cleanup pipeline |
| `plugins/ingest_website/plugin.py` | Modify | Replace early-return on empty docs with cleanup pipeline |
| `tests/plugins/test_ingest_space.py` | Modify | Add tests for empty-corpus cleanup |
| `tests/plugins/test_ingest_website.py` | Modify | Add tests for empty-corpus cleanup |

### Data Model Deltas

None. No changes to `Document`, `Chunk`, `DocumentMetadata`, `IngestResult`, `PipelineContext`, or event models.

### Interface Contracts

No changes to any port, protocol, or public API. The plugin `handle()` method signatures and return types remain identical.

## Design

### IngestSpacePlugin Changes

Replace lines 72-79 (the `if not documents: return success` block) with:

```python
if not documents:
    logger.info("Empty document list for %s; running cleanup pipeline", collection_name)
    cleanup_engine = IngestEngine(steps=[
        ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
        OrphanCleanupStep(knowledge_store_port=self._knowledge_store),
    ])
    result = await cleanup_engine.run([], collection_name)
    return IngestBodyOfKnowledgeResult(
        body_of_knowledge_id=bok_id,
        type=event.type,
        purpose=event.purpose,
        persona_id=event.persona_id,
        result="success" if result.success else "failure",
        error=ErrorDetail(message="; ".join(result.errors)) if result.errors else None,
    )
```

### IngestWebsitePlugin Changes

Replace lines 85-89 (the `if not documents: return success` block) with the same pattern:

```python
if not documents:
    logger.info("No documents extracted for %s; running cleanup pipeline", collection_name)
    cleanup_engine = IngestEngine(steps=[
        ChangeDetectionStep(knowledge_store_port=self._knowledge_store),
        OrphanCleanupStep(knowledge_store_port=self._knowledge_store),
    ])
    result = await cleanup_engine.run([], collection_name)
    return IngestWebsiteResult(
        result=IngestionResult.SUCCESS if result.success else IngestionResult.FAILURE,
        error="; ".join(result.errors) if result.errors else "",
    )
```

### How the Cleanup Works

1. `IngestEngine.run([], collection_name)` creates a `PipelineContext` with `documents=[]` and `chunks=[]`.
2. `ChangeDetectionStep` runs: `current_doc_ids` will be empty (no chunks). It fetches all existing entries from the store. All existing document IDs become `removed_document_ids`. `orphan_ids` stays empty (no per-document comparison needed since no incoming chunks exist). `change_detection_ran = True`.
3. `OrphanCleanupStep` runs: It iterates over `removed_document_ids` and deletes all chunks for each removed document (both content and summary entries).

This correctly cleans up all previously-stored data when the source returns zero documents.

## Test Strategy

### Unit Tests

| Test | Plugin | What it proves |
|------|--------|---------------|
| `test_empty_documents_runs_cleanup` | IngestSpace | Empty doc list triggers ChangeDetection + OrphanCleanup pipeline |
| `test_empty_documents_deletes_preexisting_chunks` | IngestSpace | Pre-existing chunks are actually deleted from the store |
| `test_empty_documents_runs_cleanup` | IngestWebsite | Empty crawl triggers cleanup pipeline |
| `test_empty_documents_deletes_preexisting_chunks` | IngestWebsite | Pre-existing chunks are actually deleted |
| `test_fetch_failure_does_not_cleanup` | IngestSpace | Exception path preserves error handling, no cleanup |

### Integration Test Coverage

The existing pipeline step tests in `test_pipeline_steps.py` already cover ChangeDetectionStep and OrphanCleanupStep behavior with various inputs. The new tests focus on the plugin-level branching logic.

## Rollout Notes

- Zero-config change. No new env vars, no migrations.
- Backward compatible: non-empty ingestion paths are untouched.
- Low risk: the cleanup pipeline uses existing, tested steps.
