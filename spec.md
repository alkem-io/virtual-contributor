# Spec: Handle Empty Corpus Re-Ingestion -- Run Cleanup When Source Returns Zero Documents

**Story:** #35
**Status:** Draft
**Date:** 2026-04-14

## User Value

When a body of knowledge or website that previously had content now legitimately produces zero documents (e.g., a space was emptied, a website went offline and returned no pages), the stale chunks that were previously stored must be removed from the vector knowledge store. Without this, users querying the virtual contributor will receive answers grounded in outdated/deleted content, violating data integrity expectations.

## Scope

- Modify `IngestSpacePlugin.handle()` to distinguish between "fetch succeeded but returned empty documents" and "fetch failed" scenarios.
- Modify `IngestWebsitePlugin.handle()` to distinguish between "crawl succeeded but produced no documents" and "crawl/fetch failed" scenarios.
- When a fetch succeeds with an empty result, run a minimal cleanup pipeline: `ChangeDetectionStep` + `OrphanCleanupStep` with an empty document list so that all previously stored chunks are identified as belonging to removed documents and deleted.
- When a fetch fails (exception), preserve the existing early-return / error-reporting behavior (do not touch the collection).

## Out of Scope

- Changes to the pipeline engine (`IngestEngine`) or pipeline step implementations (`steps.py`). The existing `ChangeDetectionStep` and `OrphanCleanupStep` already correctly handle an empty incoming document list -- all existing document IDs in the store will appear in `removed_document_ids`.
- Changes to event models or wire format.
- Changes to the crawler, space reader, or HTML parser.
- Changes to the `BodyOfKnowledgeSummaryStep` summary cleanup on empty corpus (the BoK summary chunk will be cleaned by `OrphanCleanupStep` via `removed_document_ids` delete-by-documentId).

## Acceptance Criteria

1. **AC-1:** When `IngestSpacePlugin` receives an event and `read_space_tree()` returns an empty list, the plugin runs `ChangeDetectionStep` + `OrphanCleanupStep` against the collection, resulting in all previously stored chunks being deleted.
2. **AC-2:** When `IngestWebsitePlugin` receives an event and the crawl + extract pipeline produces zero documents (empty pages or all pages with no extractable text), the plugin runs `ChangeDetectionStep` + `OrphanCleanupStep` against the collection, resulting in all previously stored chunks being deleted.
3. **AC-3:** When `read_space_tree()` raises an exception, `IngestSpacePlugin` returns a failure result without running any cleanup pipeline (existing behavior preserved).
4. **AC-4:** When `crawl()` raises an exception, `IngestWebsitePlugin` returns a failure result without running any cleanup pipeline (existing behavior preserved).
5. **AC-5:** Both plugins return `result="success"` for the empty-but-successful fetch scenario.
6. **AC-6:** Unit tests cover both the empty-successful and failure scenarios for each plugin.
7. **AC-7:** All existing tests continue to pass.

## Constraints

- No new dependencies.
- No changes to pipeline step implementations -- reuse existing steps.
- The cleanup pipeline must use the same `IngestEngine` orchestration as the full pipeline for consistency and metrics tracking.
- The collection name derivation logic must remain identical to the full-pipeline path.

## Clarifications

### Iteration 1

| # | Ambiguity | Chosen Answer | Rationale |
|---|-----------|--------------|-----------|
| C1 | IngestWebsitePlugin: does "empty-but-successful" include cases where the crawl returned pages but text extraction produced zero documents? | Yes. "Empty-but-successful" means the fetch+extract pipeline succeeded but the resulting document list is empty, regardless of whether the crawler returned raw pages. | The purpose is to clean up stale content. Zero usable documents means stale chunks should be removed. |
| C2 | IngestSpacePlugin: is `read_space_tree()` returning `[]` (because the space has no content or was not found) a failure or empty-but-successful? | Always treated as empty-but-successful. Exceptions from the GraphQL layer indicate actual failures. | The GraphQL query succeeded. Empty or missing space content means zero documents should exist in the store. |
| C3 | Will the BoK summary chunk (`documentId="body-of-knowledge-summary"`) be cleaned up when the corpus becomes empty? | No -- this is a pre-existing gap. The BoK summary chunk has `embeddingType="summary"` and is not tracked in `removed_document_ids` by the current change detection logic. Out of scope for this story. | Keeping scope tight. The gap is orthogonal and pre-existing. |
| C4 | Does the cleanup pipeline need `BaseConfig()` or summarization steps? | No. The cleanup pipeline only runs `ChangeDetectionStep` + `OrphanCleanupStep`. | Minimal pipeline; no summarization needed for empty corpus. |
| C5 | Should the empty-but-successful scenario be logged? | Yes, info-level log before running the cleanup pipeline. | Observability for operators. |
