# Quickstart: Content-Hash Deduplication and Orphan Cleanup

**Feature**: 006-content-hash-dedup | **Date**: 2026-04-06

## Overview

This feature converts the ingestion pipeline from "delete-and-rebuild" to incremental upsert with content-hash deduplication. After implementation, re-ingesting an unchanged corpus skips embedding entirely, and re-ingesting with changed chunking parameters automatically cleans up orphaned chunks.

## Implementation Order

### Layer 1: Port & Adapter (foundation)

1. **Add `GetResult` dataclass** to `core/ports/knowledge_store.py`
2. **Add `get()` and `delete()` methods** to `KnowledgeStorePort` protocol
3. **Implement `get()` and `delete()`** in `core/adapters/chromadb.py`
4. **Test adapter methods** — unit tests with mock ChromaDB client

### Layer 2: Data Model Changes

5. **Add `content_hash` field** to `Chunk` in `core/domain/ingest_pipeline.py`
6. **Add dedup tracking fields** to `PipelineContext` in `core/domain/pipeline/engine.py`
7. **Add `chunks_skipped` and `chunks_deleted`** to `IngestResult`

### Layer 3: Pipeline Steps (core logic)

8. **Implement `ContentHashStep`** — compute SHA-256 for content chunks
9. **Implement `ChangeDetectionStep`** — query store, mark unchanged, identify orphans
10. **Modify `StoreStep`** — use content-hash IDs for content chunks, store original `documentId` in metadata
11. **Modify `DocumentSummaryStep`** — skip unchanged documents
12. **Implement `OrphanCleanupStep`** — delete orphans and removed document chunks
13. **Propagate dedup metrics** — wire `chunks_skipped`/`chunks_deleted` from context to `IngestResult` in `IngestEngine.run()`

### Layer 4: Plugin Integration

14. **Modify `IngestSpacePlugin`** — remove `delete_collection()`, wire new steps into pipeline
15. **Modify `IngestWebsitePlugin`** — remove `delete_collection()`, wire new steps into pipeline

### Layer 5: Tests

16. **Content hash unit tests** — determinism, sensitivity to each metadata field, stability across runs
17. **ChangeDetectionStep tests** — unchanged skip, new chunk detection, orphan identification, fallback on store failure
18. **OrphanCleanupStep tests** — orphan deletion, removed document cleanup, idempotent on empty sets
19. **StoreStep tests** — content-hash ID generation, metadata `documentId` correctness
20. **Integration tests** — full pipeline: ingest → re-ingest unchanged → verify skip rate; ingest → re-ingest changed → verify orphan cleanup

### Layer 6: ADR

21. **Write ADR** — document port extension decision and content-addressable storage scheme in `docs/adr/`

## Key Files to Touch

| File | Change Type |
|---|---|
| `core/ports/knowledge_store.py` | Extend (add `GetResult`, `get()`, `delete()`) |
| `core/adapters/chromadb.py` | Extend (implement `get()`, `delete()`) |
| `core/domain/ingest_pipeline.py` | Extend (`content_hash` on Chunk, metrics on IngestResult) |
| `core/domain/pipeline/engine.py` | Extend (dedup fields on PipelineContext, propagate metrics) |
| `core/domain/pipeline/steps.py` | Extend (3 new steps) + Modify (StoreStep, DocumentSummaryStep) |
| `core/domain/pipeline/__init__.py` | Extend (export new steps) |
| `plugins/ingest_space/plugin.py` | Modify (remove delete_collection, wire new steps) |
| `plugins/ingest_website/plugin.py` | Modify (remove delete_collection, wire new steps) |
| `tests/core/domain/test_content_hash.py` | New |
| `tests/core/domain/test_pipeline_steps.py` | Extend |

## Verification

```bash
# Run all tests
poetry run pytest

# Run only dedup-related tests
poetry run pytest tests/core/domain/test_content_hash.py tests/core/domain/test_pipeline_steps.py -v

# Lint and type check
poetry run ruff check core/ plugins/ tests/
poetry run pyright core/ plugins/
```

## Expected Behavior After Implementation

| Scenario | Before | After |
|---|---|---|
| Re-ingest unchanged corpus | Delete collection → re-embed everything | Skip all embeddings (>80% skip rate) |
| Re-ingest with changed chunk size | Delete collection → re-embed everything | Embed only new chunks, delete orphans |
| Document removed from source | Delete collection → re-embed remaining | Delete removed document's chunks, keep rest |
| First ingestion | Delete collection → embed all | Embed all (identical behavior, no collection to delete) |
| Legacy data (no fingerprints) | N/A | All chunks treated as new, re-embedded, old chunks become orphans and are cleaned up |
