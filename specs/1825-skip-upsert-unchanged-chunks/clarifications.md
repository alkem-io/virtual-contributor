# Clarifications: Skip upsert for unchanged chunks in StoreStep

**Story:** alkem-io/alkemio#1825

## Iteration 1

### Q1: How should unchanged chunks interact with the "skipped without embeddings" error message?

**Question:** Currently StoreStep counts `len(context.chunks) - len(storable)` as skipped. After filtering unchanged chunks, should the "skipped" count reflect chunks missing embeddings from all chunks, or only from the non-unchanged subset?

**Answer:** Filter unchanged chunks first, then compute the "skipped without embeddings" count from the remaining pool. This way the error message accurately reflects actual embedding failures rather than conflating them with intentionally skipped unchanged chunks.

**Rationale:** Mixing unchanged-skip counts with embedding-missing counts would produce misleading error messages. The two skips have different causes: one is healthy optimization, the other indicates a pipeline failure.

### Q2: What log level for the unchanged-chunks-skipped message?

**Question:** Should the new log message reporting unchanged chunks skipped by StoreStep be at INFO, DEBUG, or WARNING level?

**Answer:** INFO level.

**Rationale:** Consistent with the existing `ChangeDetectionStep` logging at line 228 of steps.py which logs skip/change counts at INFO.

### Q3: Does IngestResult.chunks_stored need separate handling?

**Question:** `IngestResult.chunks_stored` is set from `context.chunks_stored` in `engine.py`. Does it need modification?

**Answer:** No. Since `context.chunks_stored` is only incremented when `store.ingest()` is actually called, and we are filtering unchanged chunks before that call, the count will naturally be correct without any changes to `IngestEngine`.

**Rationale:** The engine just reads `context.chunks_stored` at the end. The fix is self-contained in StoreStep.

### Q4: Should the filter guard against None content_hash?

**Question:** The filter `c.content_hash not in context.unchanged_chunk_hashes` works correctly even when `c.content_hash is None` because `None` will never be in the set of string hashes. Should we add an explicit `is not None` guard anyway?

**Answer:** Yes, include `c.content_hash is not None` in the filter for readability and defensive coding.

**Rationale:** Explicit guards prevent future breakage if someone adds None to the set, and make the intent immediately obvious to readers.

### Q5: Should we use the issue's proposed approach (filter on unchanged_chunk_hashes) or the alternative (add a `changed` flag to Chunk)?

**Question:** The issue offers two approaches. Which one?

**Answer:** Use the `unchanged_chunk_hashes` filter approach. Do not add a `changed` flag to `Chunk`.

**Rationale:** The `unchanged_chunk_hashes` set already exists on `PipelineContext` and is populated by `ChangeDetectionStep`. Adding a field to `Chunk` would change the data model for a single consumer, violating the minimal-change principle. The set-based approach is zero-cost at the model layer.

## Iteration 2

No new ambiguities found. All questions resolved.
