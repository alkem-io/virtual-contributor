# Quickstart: Handle Empty Corpus Re-Ingestion

**Feature Branch**: `story/35-handle-empty-corpus-reingestion-cleanup`
**Date**: 2026-04-14

## What This Feature Does

Fixes a bug where previously stored chunks remain in the vector knowledge store when a space or website that previously had content returns zero documents on re-ingestion. Both `IngestSpacePlugin` and `IngestWebsitePlugin` now run a minimal cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) to delete all stale chunks when the fetch/crawl succeeds but produces zero documents.

No new configuration, no new dependencies, no behavioral change for non-empty ingestion.

## Quick Verification

### 1. Empty space cleanup

```bash
# 1. Ingest a space with content (creates chunks in the collection)
export PLUGIN_TYPE=ingest-space
poetry run python main.py
# Send an ingest event for a space with documents

# 2. Remove all content from the space in Alkemio UI

# 3. Re-ingest the same space
# Send another ingest event for the same space

# Expected: INFO log "Space <id> returned zero documents; running cleanup pipeline for collection <name>"
# Expected: All previously stored chunks are deleted
# Expected: Result is "success"
```

### 2. Empty website cleanup

```bash
# 1. Ingest a website with pages (creates chunks in the collection)
export PLUGIN_TYPE=ingest-website
poetry run python main.py
# Send an ingest event for a website with pages

# 2. Take the website offline or remove all content

# 3. Re-ingest the same website
# Send another ingest event for the same website

# Expected: INFO log "Website <url> produced zero documents; running cleanup pipeline for collection <name>"
# Expected: All previously stored chunks are deleted
# Expected: Result is "success"
```

### 3. Failure behavior preserved

```bash
# When the fetch/crawl raises an exception (e.g., network failure):
# Expected: Result is "failure" with error details
# Expected: No cleanup runs -- knowledge store untouched
```

### 4. Run tests

```bash
poetry run pytest tests/plugins/test_ingest_space.py -v
poetry run pytest tests/plugins/test_ingest_website.py -v
poetry run pytest  # Full suite -- zero regressions
```

## Files Changed

| File | Change |
|------|--------|
| `plugins/ingest_space/plugin.py` | Replace early return on empty documents with cleanup pipeline run (~15 lines) |
| `plugins/ingest_website/plugin.py` | Replace early return on empty documents with cleanup pipeline run (~15 lines) |
| `tests/plugins/test_ingest_space.py` | Add 3 tests: empty-cleanup, empty-returns-success, failure-no-cleanup |
| `tests/plugins/test_ingest_website.py` | Add 4 tests: empty-crawl-cleanup, empty-extract-cleanup, empty-returns-success, failure-no-cleanup; rename `test_unsupported_content_skip` |

## Contracts

No external interface changes:
- **KnowledgeStorePort**: Unchanged (cleanup pipeline uses existing `delete` operations via steps)
- **PluginContract**: Unchanged (no new lifecycle methods, same `handle()` signature and return types)
- **Event schemas**: Unchanged
- **IngestEngine**: Unchanged (instantiated with a subset of steps, which is already supported)
