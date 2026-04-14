# Clarifications: Story #36

## Iteration 1

### Q1: Should stale summary cleanup only apply to changed documents, or also unchanged ones that happen to be below threshold?

**Chosen Answer:** Only changed documents. If a document is unchanged (not in `changed_document_ids`), its chunk count has not changed since last ingestion, so its summary state is already correct. The cleanup should target documents in `changed_document_ids` that now fall below the threshold.

**Rationale:** The issue text explicitly says "changed documents that no longer qualify" and the proposed approach references `doc_id in changed_document_ids`. Unchanged documents already have consistent summary state.

### Q2: What if change detection did not run (`change_detection_ran is False`)? Should stale summary cleanup still apply?

**Chosen Answer:** No. When change detection has not run, there is no `changed_document_ids` set to reference, and we cannot know which documents previously had summaries. The cleanup logic should only fire when `context.change_detection_ran is True`.

**Rationale:** Without change detection, the pipeline treats all chunks as new (per the fallback in `ChangeDetectionStep`). The summary step already gates its selective behavior on `change_detection_ran`. Stale cleanup should follow the same guard.

### Q3: The storage ID for summary chunks uses pattern `{doc_id}-summary-{chunk_index}`. Should we clean up all possible summary chunk indices or only index 0?

**Chosen Answer:** Only index 0. The current `DocumentSummaryStep` always produces exactly one summary chunk per document with `chunk_index=0`, yielding storage ID `{doc_id}-summary-0`. There is no multi-chunk summary support.

**Rationale:** Inspecting `StoreStep`, summary chunks get ID `f"{c.metadata.document_id}-{c.chunk_index}"`. The `DocumentSummaryStep` always sets `chunk_index=0`. The issue also explicitly references the `-summary-0` pattern.

### Q4: Should `BodyOfKnowledgeSummaryStep` check for the empty-corpus condition before or after the existing early-return guard?

**Chosen Answer:** After the existing early-return guard (which checks for no changes and no removals). The empty-corpus condition only matters when there ARE removals (all documents removed). The early-return guard already passes through when `removed_document_ids` is non-empty, so the new check goes after it, in the position where `seen_doc_ids` is computed and found empty.

**Rationale:** The existing guard `if change_detection_ran and not changed_document_ids and not removed_document_ids: return` already handles the "nothing happened" case. The empty-corpus case requires `removed_document_ids` to be non-empty, which passes that guard. The new logic replaces the bare `if not seen_doc_ids: return` with the orphan-marking behavior.

### Q5: Should the BoK cleanup also handle the case where change detection did not run?

**Chosen Answer:** No. If change detection did not run, `removed_document_ids` will be empty (it is populated solely by `ChangeDetectionStep`). The condition `removed_document_ids is non-empty` inherently requires change detection to have run.

**Rationale:** The dataclass field `removed_document_ids` defaults to an empty set. Only `ChangeDetectionStep` populates it. So the guard is implicit.
