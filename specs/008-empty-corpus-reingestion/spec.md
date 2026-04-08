# Spec: Handle Empty Corpus Re-ingestion

**Story:** #35 — Handle empty corpus re-ingestion: run cleanup when source returns zero documents
**Status:** Draft
**Date:** 2026-04-08

## User Value

When a body of knowledge or website that previously had indexed content is emptied or deleted at the source, the virtual contributor should stop returning stale answers from the old content. Currently, stale chunks persist indefinitely because the empty-result early-return path bypasses the change-detection and orphan-cleanup pipeline steps.

## Scope

1. Modify `IngestSpacePlugin.handle()` to distinguish between "fetch succeeded, zero documents" and "fetch failed" and run a cleanup-only pipeline on empty-but-successful fetch.
2. Modify `IngestWebsitePlugin.handle()` with the same logic: distinguish "crawl returned zero pages/documents" from "crawl raised an exception" and run cleanup on empty-but-successful crawl.
3. The cleanup-only pipeline consists of `ChangeDetectionStep` and `OrphanCleanupStep` only (no Chunk, Hash, Embed, Store, or Summary steps), invoked with an empty document list so that all existing chunks are flagged as belonging to removed documents and deleted.
4. Add unit tests covering the new behavior for both plugins.

## Out of Scope

- Changes to the pipeline engine itself (`IngestEngine`, `PipelineContext`).
- Changes to the `ChangeDetectionStep` or `OrphanCleanupStep` implementations (they already handle the empty-input case correctly by design: when current_doc_ids is empty, all existing_doc_ids become removed_document_ids).
- Retry/backoff logic for failed fetches.
- Partial-failure scenarios (e.g., crawl succeeds for some pages but fails for others).

## Acceptance Criteria

1. **AC-1:** When `IngestSpacePlugin` receives an event and `read_space_tree()` returns an empty list, the plugin runs `ChangeDetectionStep` + `OrphanCleanupStep` against the collection and reports success.
2. **AC-2:** When `IngestWebsitePlugin` receives an event and crawling yields zero extractable documents, the plugin runs `ChangeDetectionStep` + `OrphanCleanupStep` against the collection and reports success.
3. **AC-3:** When fetching/crawling raises an exception, the existing early-return/failure behavior is preserved (no cleanup runs, error is reported).
4. **AC-4:** Unit tests prove that previously-stored chunks are deleted when an empty corpus is re-ingested.
5. **AC-5:** All existing tests continue to pass.

## Constraints

- No new dependencies.
- Pipeline steps (`ChangeDetectionStep`, `OrphanCleanupStep`) must not be modified; the fix is entirely in the plugin layer.
- The cleanup pipeline must reuse the existing `IngestEngine` to maintain observability (metrics, logging).

## Clarifications

### Iteration 1

| # | Ambiguity | Resolution | Rationale |
|---|-----------|------------|-----------|
| 1 | **IngestWebsitePlugin: crawl returns empty list for both "no pages" and "network error handled internally"** -- the crawler silently swallows per-page exceptions and returns `[]` when all requests fail. How do we distinguish "fetch succeeded, nothing found" from "fetch failed"? | Treat crawl as successful whenever `crawl()` returns without raising. The crawler already logs warnings for individual page failures. An empty return from `crawl()` means "no usable pages found" and should trigger cleanup. Only an unhandled exception (which propagates out of `crawl()`) is treated as a fetch failure. | The crawler's contract is: exceptions mean infrastructure failure; empty list means no content. The caller already wraps the entire flow in try/except. This aligns with the existing error model. |
| 2 | **IngestSpacePlugin: `read_space_tree()` returns empty when the space itself is not found (lookup returns None)** -- is "space not found" a failure or a legitimate empty result? | Treat it as a legitimate empty result that triggers cleanup. If a space was deleted, we want its stale chunks removed. | A deleted space is the primary scenario this story targets. Returning empty-but-successful is the correct behavior. |
| 3 | **Should the cleanup-only pipeline report `result="success"` or a distinct status like `"cleaned"`?** | Report `"success"`. | Both plugins already return success/failure as their only result states. Adding a third value would require downstream consumer changes, which is out of scope. The logged pipeline metrics provide sufficient observability. |
| 4 | **IngestWebsitePlugin: the current early return says `error="No content extracted"`. Should that message be preserved or changed for the cleanup case?** | Remove the error string for the cleanup case. On successful cleanup, the result is success with no error. The old early-return message was misleading since it implied a problem when there was none. | Cleanup of an empty corpus is a normal operational outcome, not an error. Returning an error string alongside a success status is semantically inconsistent. |
| 5 | **Should the cleanup pipeline include any logging to distinguish it from a full pipeline run?** | Yes, add an info-level log line before running the cleanup-only pipeline, e.g., "No documents found; running cleanup-only pipeline for collection {name}". | Operators need to be able to distinguish a cleanup-only run from a full ingest run in logs for debugging purposes. |
