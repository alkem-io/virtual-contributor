# Research: Handle Empty Corpus Re-Ingestion

**Feature Branch**: `story/35-handle-empty-corpus-reingestion-cleanup`
**Date**: 2026-04-14

## Research Tasks

### R1: Can existing pipeline steps handle an empty document list?

**Context**: Both `IngestSpacePlugin` and `IngestWebsitePlugin` return early when the fetched document list is empty. After the content-hash dedup change, this bypasses `ChangeDetectionStep` and `OrphanCleanupStep`, leaving stale chunks in the knowledge store. The question is whether the existing steps can correctly handle being run with an empty document list.

**Findings**:

The `ChangeDetectionStep` logic when given an empty document list:
1. `current_doc_ids` is empty (no incoming documents)
2. Queries the knowledge store for all existing document IDs in the collection
3. Since `current_doc_ids` is empty, ALL existing document IDs appear in `removed_document_ids`
4. The step correctly marks everything as removed

The `OrphanCleanupStep` then:
1. Iterates over `removed_document_ids`
2. Deletes all chunks for each removed document ID
3. This correctly removes all stale chunks

No changes needed to pipeline step implementations.

**Decision**: Reuse existing `ChangeDetectionStep` and `OrphanCleanupStep` with an empty document list.
**Rationale**: The steps already handle the empty case correctly by design. No new code needed in `steps.py`.
**Alternatives considered**: (a) Direct `knowledge_store.delete_collection()` call -- rejected (loses metrics tracking and consistency with normal pipeline flow). (b) Custom cleanup method on plugins -- rejected (duplicates logic already in pipeline steps).

---

### R2: Minimal pipeline composition

**Context**: The full ingest pipeline includes `ChunkStep`, `ContentHashStep`, `ChangeDetectionStep`, `EmbedStep`, `StoreStep`, `DocumentSummaryStep`, `BodyOfKnowledgeSummaryStep`, and `OrphanCleanupStep`. Which subset is needed for cleanup?

**Findings**:

For an empty document list:
- `ChunkStep`: Not needed (no documents to chunk)
- `ContentHashStep`: Not needed (no chunks to hash)
- `ChangeDetectionStep`: NEEDED (identifies which document IDs have been removed)
- `EmbedStep`: Not needed (no new chunks to embed)
- `StoreStep`: Not needed (no new chunks to store)
- `DocumentSummaryStep`: Not needed (no documents to summarize)
- `BodyOfKnowledgeSummaryStep`: Not needed (no summaries to aggregate)
- `OrphanCleanupStep`: NEEDED (deletes chunks for removed document IDs)

The minimal pipeline is: `[ChangeDetectionStep, OrphanCleanupStep]`.

**Decision**: Instantiate `IngestEngine` with only `[ChangeDetectionStep, OrphanCleanupStep]` for the cleanup pipeline.
**Rationale**: Minimal step set that achieves the goal. Uses `IngestEngine` for consistency and metrics tracking.
**Alternatives considered**: (a) Run the full pipeline with empty input -- rejected (unnecessary steps slow down the operation and may have side effects like creating empty summaries). (b) Call steps directly without `IngestEngine` -- rejected (loses orchestration, error handling, and metrics).

---

### R3: Distinguishing "empty-but-successful" from "fetch failure"

**Context**: Both plugins have try/except blocks around the fetch/crawl operation. The question is how to distinguish between a successful fetch that returned zero documents vs. a failed fetch that raised an exception.

**Findings**:

In both plugins, the fetch/crawl call is inside a try/except block:
- **Success path**: Function returns normally (possibly with an empty list)
- **Failure path**: Function raises an exception, caught by the outer `except` block

The `not documents` check already correctly identifies the empty-but-successful case:
- `read_space_tree()` returns `[]` when the space has no content
- `crawl()` returns `[]` when no pages are found
- Text extraction may produce zero `Document` objects from non-empty crawl results

The failure path (exception) is handled by existing error handling code that returns failure without any cleanup. This behavior must be preserved.

**Decision**: Keep the existing `not documents` check as the branch point. Replace the early return with cleanup pipeline invocation. Leave the exception handling unchanged.
**Rationale**: The existing control flow already correctly distinguishes the two cases. Minimal change: only the body of the `if not documents` block changes.
**Alternatives considered**: (a) Add explicit success/failure enum to fetch results -- rejected (over-engineering for this use case; the existing pattern is clear and consistent).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Pipeline step reuse | Existing steps handle empty list correctly | No changes needed to `steps.py` |
| Minimal pipeline | `[ChangeDetectionStep, OrphanCleanupStep]` | Only steps needed for cleanup |
| Empty vs. failure | Reuse existing `not documents` check + try/except | Already correctly distinguishes the cases |
| Pipeline orchestration | Use `IngestEngine` (not direct step calls) | Consistency, metrics, error handling |
