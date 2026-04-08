# Specification: Handle Empty Corpus Re-ingestion

**Story**: alkem-io/virtual-contributor#35
**Epic**: alkem-io/alkemio#1820
**Date**: 2026-04-08

## User Value

When a body of knowledge or website that previously had content is re-ingested and the source now legitimately returns zero documents, the system must clean up all previously-stored chunks so that stale data does not remain queryable. Without this, users querying the knowledge base get answers sourced from content that no longer exists.

## Scope

1. **IngestSpacePlugin** (`plugins/ingest_space/plugin.py`): Modify the empty-document early-return path to distinguish "fetch succeeded, empty result" from "fetch failed", and run a cleanup-only pipeline on successful-but-empty fetch.
2. **IngestWebsitePlugin** (`plugins/ingest_website/plugin.py`): Same treatment for the crawl-then-extract path.
3. **Pipeline integration**: The cleanup-only pipeline consists of `ChangeDetectionStep` + `OrphanCleanupStep` running against an empty document list, so all existing chunks are identified as belonging to removed documents and deleted.
4. **Tests**: New unit tests covering the empty-corpus cleanup path for both plugins, verifying that previously-stored chunks are deleted.

## Out of Scope

- Changes to `ChangeDetectionStep` or `OrphanCleanupStep` internal logic (they already handle empty document lists correctly -- all existing doc IDs will appear in `removed_document_ids`).
- Changes to the `IngestEngine` or `PipelineContext`.
- Changes to the pipeline step ordering for normal (non-empty) ingestion flows.
- Fetch failure handling changes (existing early-return-on-error behavior is preserved).

## Acceptance Criteria

1. When `read_space_tree()` succeeds but returns an empty list, the plugin runs `ChangeDetectionStep` + `OrphanCleanupStep` against the empty list, causing all previously-stored chunks to be deleted.
2. When crawl + extract produces zero documents (successful fetch, no content), the website plugin runs the same cleanup pipeline.
3. When the fetch itself fails (exception), both plugins preserve existing early-return/error behavior -- no cleanup is performed.
4. Both plugins return a success result after cleanup-only runs.
5. Unit tests verify that previously-stored chunks are removed after an empty-corpus re-ingestion for both plugins.

## Constraints

- Must not break existing non-empty ingestion flows.
- Must not call `delete_collection()` -- the content-hash dedup approach (ADR 0006) uses per-chunk cleanup, not collection-level deletion.
- The cleanup-only pipeline must not include `ChunkStep`, `ContentHashStep`, `EmbedStep`, `StoreStep`, or summarization steps -- only `ChangeDetectionStep` + `OrphanCleanupStep`.
- The fix must be backward-compatible with the existing plugin contract (duck-typed `PluginContract` protocol).

## Clarifications

**Iteration 1** (5 ambiguities resolved, 0 remaining):

| # | Ambiguity | Resolution | Rationale |
|---|-----------|------------|-----------|
| 1 | Should IngestWebsitePlugin distinguish "crawl returned zero pages" from "pages returned but all empty text"? | Treat both as successful-but-empty. | The current code already filters empty-text pages before the `if not documents` check. Both cases mean "no content to ingest". |
| 2 | Should cleanup-only pipeline return a different status than normal ingestion? | Return "success". | The operation completed as intended. Logging distinguishes the two paths. |
| 3 | Should IngestWebsitePlugin cleanup use the same collection_name derivation? | Yes, same `{netloc}-knowledge` formula. | Cleanup must target the same collection where chunks were stored. |
| 4 | If GraphQL client is not configured in IngestSpacePlugin, should we attempt cleanup? | No. Preserve existing RuntimeError path. | Cannot distinguish "source empty" from "config broken" without a working client. |
| 5 | Should cleanup actions be logged? | Yes, info-level log when running cleanup-only pipeline. | Observability for operators when a corpus is emptied. |
