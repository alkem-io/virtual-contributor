# Spec: Handle Empty Corpus Re-ingestion

**Story:** #35 -- Handle empty corpus re-ingestion -- run cleanup when source returns zero documents
**Status:** Draft
**Author:** SDD Agent
**Date:** 2026-04-08

---

## User Value

When a body of knowledge or website previously contained content but now legitimately returns zero documents (e.g., a space was emptied, a website was taken down), all previously-stored chunks must be cleaned up. Without this fix, stale data remains queryable indefinitely, leading to misleading or incorrect answers from the virtual contributor.

## Scope

- **IngestSpacePlugin**: Replace the early-return on empty documents with a minimal cleanup pipeline (ChangeDetectionStep + OrphanCleanupStep) that removes all previously-stored chunks.
- **IngestWebsitePlugin**: Same treatment -- run cleanup pipeline on empty-but-successful fetch.
- Preserve existing early-return behavior when the fetch itself fails (exception path).
- Add unit tests proving both empty-corpus cleanup and fetch-failure preservation.

## Out of Scope

- Changes to the pipeline engine itself (IngestEngine, PipelineContext, PipelineStep protocol).
- Changes to ChangeDetectionStep or OrphanCleanupStep internals -- these already handle the "all existing docs are removed" case correctly when given an empty document list.
- Changes to non-ingest plugins (expert, generic, guidance, openai_assistant).
- Changes to event models or wire format.

## Acceptance Criteria

1. **AC-1**: When `IngestSpacePlugin` receives an empty document list from `read_space_tree`, it runs `ChangeDetectionStep` + `OrphanCleanupStep` with an empty document list against the correct collection, deleting all previously-stored chunks.
2. **AC-2**: When `IngestWebsitePlugin` crawl succeeds but produces zero extractable documents, it runs `ChangeDetectionStep` + `OrphanCleanupStep` with an empty document list against the correct collection, deleting all previously-stored chunks.
3. **AC-3**: When the fetch itself fails (exception in `read_space_tree` or `crawl`), the existing error-handling behavior is preserved -- no cleanup is attempted.
4. **AC-4**: The cleanup pipeline result is reflected in the return value: success if cleanup succeeds, failure with error detail if cleanup fails.
5. **AC-5**: Unit tests cover both plugins for: (a) empty-but-successful fetch triggers cleanup, (b) pre-existing chunks are deleted, (c) fetch failure does not trigger cleanup.

## Constraints

- Must not break existing non-empty ingestion flows.
- Must use the existing `IngestEngine` with `ChangeDetectionStep` + `OrphanCleanupStep` -- no ad-hoc deletion logic.
- Must maintain the current plugin contract (duck-typed PluginContract protocol).
- Python 3.12, async throughout.
