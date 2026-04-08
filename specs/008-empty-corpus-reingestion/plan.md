# Plan: Handle Empty Corpus Re-ingestion

**Story:** #35
**Date:** 2026-04-08

## Architecture

This change is confined to the plugin layer. No changes to core domain, pipeline engine, pipeline steps, ports, adapters, or events.

### Current Flow

```
Plugin.handle(event)
  -> fetch documents (GraphQL / crawl)
  -> if not documents: return success (EARLY EXIT -- bug)
  -> IngestEngine([Chunk, Hash, ChangeDetection, Summary, Embed, Store, OrphanCleanup]).run(documents)
  -> return result
```

### Proposed Flow

```
Plugin.handle(event)
  -> fetch documents (GraphQL / crawl)
  -> if not documents:
       -> log "No documents found; running cleanup-only pipeline"
       -> IngestEngine([ChangeDetection, OrphanCleanup]).run([], collection_name)
       -> return result based on pipeline outcome
  -> IngestEngine([full pipeline]).run(documents)
  -> return result
```

The key insight is that `ChangeDetectionStep` already handles the empty-input case correctly: when `current_doc_ids` is empty, `removed_document_ids = existing_doc_ids - {} = existing_doc_ids`, so all existing documents are flagged for removal. `OrphanCleanupStep` then deletes all chunks belonging to those removed documents.

## Affected Modules

| Module | Change | Risk |
|--------|--------|------|
| `plugins/ingest_space/plugin.py` | Replace early return with cleanup pipeline | Low -- localized change, no interface changes |
| `plugins/ingest_website/plugin.py` | Replace early return with cleanup pipeline | Low -- localized change, no interface changes |
| `tests/plugins/test_ingest_space.py` | Add test for empty corpus cleanup | None |
| `tests/plugins/test_ingest_website.py` | Add test for empty corpus cleanup | None |

## Data Model Deltas

None. No schema changes, no new fields, no migration needed.

## Interface Contracts

No interface changes. Both plugins continue to accept the same event types and return the same result types. The `IngestEngine` API is unchanged.

## Test Strategy

### Unit Tests (new)

1. **`test_empty_corpus_cleanup_deletes_stale_chunks` (ingest_space):** Pre-populate MockKnowledgeStorePort with existing chunks, mock `read_space_tree` to return `[]`, invoke `handle()`, assert that the collection is now empty (chunks deleted via OrphanCleanupStep).

2. **`test_empty_corpus_cleanup_deletes_stale_chunks` (ingest_website):** Pre-populate MockKnowledgeStorePort with existing chunks, mock `crawl` to return `[]`, invoke `handle()`, assert that the collection is now empty.

3. **`test_fetch_failure_preserves_collection` (ingest_space):** Mock `read_space_tree` to raise, invoke `handle()`, assert chunks are NOT deleted and result is failure.

4. **`test_crawl_with_empty_pages_runs_cleanup` (ingest_website):** Mock `crawl` to return pages with no extractable text, invoke `handle()`, assert cleanup runs.

### Existing Tests (regression)

All existing tests must continue to pass. The change only affects the `if not documents` branch, which existing tests do exercise but only assert on result status, not on cleanup behavior.

## Rollout Notes

- No configuration changes needed.
- No environment variable changes.
- Backward compatible: the change only affects behavior when documents are empty, which was previously a no-op.
- Deployable independently; no coordination with other services required.
