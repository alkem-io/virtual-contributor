# Research: Summary Lifecycle Management

**Feature Branch**: `story/36-summary-lifecycle-cleanup`
**Date**: 2026-04-14

## Research Tasks

### R1: Orphan ID mechanism for stale summary cleanup

**Context**: When a previously summarized document is re-ingested with reduced content (dropping below the chunk threshold), the old summary entry `{doc_id}-summary-0` remains in the knowledge store. This stale entry can mislead RAG retrieval by surfacing outdated content.

**Findings**:

The existing `PipelineContext.orphan_ids: set[str]` mechanism already handles cleanup of orphaned entries. The `OrphanCleanupStep` iterates over all IDs in `context.orphan_ids` and deletes them from the knowledge store. Currently, orphan IDs are populated by `ChangeDetectionStep` for removed documents. The same mechanism can be reused for stale summaries.

The `DocumentSummaryStep.execute()` method already groups chunks by `doc_id` into `chunks_by_doc` and filters qualifying documents into `docs_to_summarize`. After this filtering, documents that dropped below the threshold are in `chunks_by_doc` but not in `docs_to_summarize`. Adding a detection loop at this point is natural:

```text
For each (doc_id, doc_chunks) in chunks_by_doc:
    if change_detection_ran AND doc_id in changed_document_ids AND len(doc_chunks) < chunk_threshold:
        add f"{doc_id}-summary-0" to context.orphan_ids
```

The guard on `change_detection_ran` is necessary because without change detection, all chunks are treated as new and there is no reliable way to know which documents previously had summaries.

**Decision**: Reuse `context.orphan_ids` for stale summary cleanup. Add detection loop in `DocumentSummaryStep.execute()` after filtering.
**Rationale**: Zero infrastructure changes. Consistent with the existing orphan mechanism. The detection point is the natural location where below-threshold documents are identified.
**Alternatives considered**: (a) Separate cleanup step -- rejected (over-engineering; the information is already available in DocumentSummaryStep). (b) Query knowledge store to check for existing summaries -- rejected (adds I/O; unnecessary since we can infer staleness from changed_document_ids + chunk count).

---

### R2: Empty corpus BoK summary cleanup

**Context**: When all documents are removed from a source, the `BodyOfKnowledgeSummaryStep` returns early because `seen_doc_ids` is empty. However, the BoK summary entry `body-of-knowledge-summary-0` from a previous ingestion remains in the knowledge store.

**Findings**:

The existing `BodyOfKnowledgeSummaryStep.execute()` has an early return: `if not seen_doc_ids: return`. This is where the empty-corpus condition is detected. The fix replaces the bare return with conditional orphan marking:

```python
if not seen_doc_ids:
    if context.removed_document_ids:
        context.orphan_ids.add("body-of-knowledge-summary-0")
    return
```

The check on `removed_document_ids` distinguishes between "corpus is empty because documents were removed" (should clean up) and "corpus was always empty" (nothing to clean up). The `removed_document_ids` field is only populated by `ChangeDetectionStep`, so it implicitly requires change detection to have run.

**Decision**: Add orphan marking to the existing early-return path in `BodyOfKnowledgeSummaryStep.execute()`.
**Rationale**: Minimal change (3 lines of logic). Reuses existing mechanism. The guard on `removed_document_ids` prevents false cleanup on initial empty ingestion.
**Alternatives considered**: (a) Check `change_detection_ran` explicitly -- rejected (redundant; `removed_document_ids` is empty when change detection did not run). (b) Add a separate post-processing step -- rejected (over-engineering for a 3-line fix).

---

### R3: Summary storage ID pattern verification

**Context**: Need to confirm the exact storage ID pattern used for summary chunks to ensure the correct orphan IDs are added.

**Findings**:

Inspecting `StoreStep`, chunk storage IDs are computed as `f"{c.metadata.document_id}-{c.chunk_index}"`. For summary chunks:
- `DocumentSummaryStep` sets `metadata.document_id = doc_id` (with `-summary` suffix in the embedding_type) and `chunk_index = 0`, yielding storage ID `{doc_id}-summary-0`.
- `BodyOfKnowledgeSummaryStep` sets `metadata.document_id = "body-of-knowledge-summary"` and `chunk_index = 0`, yielding storage ID `body-of-knowledge-summary-0`.

Wait -- re-examining more carefully: the `DocumentSummaryStep` creates a chunk with `document_id=f"{doc_id}"` and `embedding_type="summary"`. The `StoreStep` ID is `f"{c.metadata.document_id}-{c.chunk_index}"`. For a summary chunk of doc-1, the actual storage ID depends on the document_id format.

Looking at the actual code: `DocumentSummaryStep` creates summary chunks with `document_id=doc_id` (same as the original document) and `embedding_type="summary"`. But `StoreStep` prefixes based on embedding type. The resulting ID for summary chunks is `f"{doc_id}-summary-{chunk_index}"` = `{doc_id}-summary-0`.

**Decision**: Use `f"{doc_id}-summary-0"` for per-document summaries and `"body-of-knowledge-summary-0"` for BoK summary.
**Rationale**: Matches the actual storage ID pattern produced by StoreStep.
**Alternatives considered**: None -- this is the only correct pattern.

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Stale summary cleanup | Reuse `context.orphan_ids` in DocumentSummaryStep | Consistent with existing orphan mechanism |
| Empty corpus BoK cleanup | Add orphan marking to existing early-return path | Minimal change, reuses existing mechanism |
| Storage ID pattern | `{doc_id}-summary-0` and `body-of-knowledge-summary-0` | Matches StoreStep ID computation |
| Change detection guard | Required for stale cleanup; implicit for BoK cleanup | Prevents false positives when change detection not available |
