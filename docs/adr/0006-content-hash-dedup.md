# ADR 0006: Content-Hash Deduplication and Port Extension

**Status**: Accepted
**Date**: 2026-04-06
**Feature**: 006-content-hash-dedup

## Context

The ingestion pipeline previously used a destructive "delete-and-rebuild" approach: on every re-ingestion, the entire ChromaDB collection was deleted and all documents were re-chunked, re-embedded, and re-stored. This was wasteful when content hadn't changed, as embedding API calls are the most expensive operation in the pipeline (~ms per chunk vs ~µs for hashing).

## Decision

### 1. Content-Addressable Storage

Content chunks are stored using their SHA-256 content hash as the storage ID. The hash is computed from a canonical string of the chunk's text content and embedding-relevant metadata fields (`content`, `title`, `source`, `type`, `document_id`) joined by null-byte separators.

Summary chunks use deterministic IDs (`{document_id}-summary-{chunk_index}`) since LLM-generated summaries are non-deterministic across runs.

### 2. KnowledgeStorePort Extension

Two new methods were added to the `KnowledgeStorePort` protocol:

- `get(collection, ids?, where?, include?)` — Retrieve chunks by ID list and/or metadata filter
- `delete(collection, ids?, where?)` — Delete chunks by ID list and/or metadata filter

These complete the CRUD surface of the port (which previously only had Create via `ingest()`, Read-by-similarity via `query()`, and Delete-all via `delete_collection()`).

### 3. Three New Pipeline Steps

- **ContentHashStep** — Computes SHA-256 fingerprint for each content chunk
- **ChangeDetectionStep** — Queries the store for existing chunks, pre-loads embeddings on unchanged chunks, identifies orphans and removed documents
- **OrphanCleanupStep** — Deletes orphaned chunk IDs and chunks from removed documents

### 4. Incremental Upsert Replaces Delete-and-Rebuild

Both ingestion plugins (`IngestSpacePlugin`, `IngestWebsitePlugin`) no longer call `delete_collection()` before re-ingestion. Instead, the pipeline incrementally upserts changed chunks and cleans up orphans.

### 5. Summarization Skip via `change_detection_ran` Flag

LLM-generated summaries are non-deterministic — regenerating them on every cycle would cause semantic drift even when content is unchanged. A `change_detection_ran` boolean on `PipelineContext` disambiguates "no changes detected" from "change detection step not in pipeline":

- `DocumentSummaryStep`: skips documents not in `changed_document_ids` when the flag is `True`
- `BodyOfKnowledgeSummaryStep`: skips entirely when the flag is `True` and `changed_document_ids` is empty

When the flag is `False` (no `ChangeDetectionStep` in the pipeline), both steps behave as before — full backward compatibility.

## Consequences

- **Performance**: Re-ingesting an unchanged corpus skips all embedding calls and all LLM summarization calls (100% skip rate observed in tests)
- **Correctness**: Orphaned chunks from changed chunking parameters are automatically cleaned up; summary chunks for removed documents are also cleaned up
- **Semantic stability**: Unchanged documents retain their existing summaries and embeddings, preventing drift from non-deterministic LLM output
- **Port contract**: Any future `KnowledgeStorePort` implementations must provide `get()` and `delete()` methods
- **Backward compatibility**: `delete_collection()` is retained on the port for administrative use but is no longer called during ingestion. Pipelines without `ChangeDetectionStep` behave identically to before.
- **Crash safety**: `OrphanCleanupStep` runs after `StoreStep` — new chunks are safely stored before orphans are deleted
