# Clarifications: Incremental Embedding

**Story:** alkem-io/alkemio#1826
**Clarify iterations:** 2 (iteration 1 produced 6 ambiguities; iteration 2 produced 0)

## Resolved Ambiguities

### C1: Scope of per-document embedding
**Question:** Should DocumentSummaryStep embed only content chunks, or also the summary chunk it creates?
**Answer:** Both. Embed the document's content chunks AND the new summary chunk immediately after summarization.
**Rationale:** The summary chunk belongs to that document and would otherwise wait for the global EmbedStep. Embedding it immediately maximizes overlap benefit.

### C2: embeddings_port parameter optionality
**Question:** Should the embeddings_port parameter be required or optional in DocumentSummaryStep?
**Answer:** Optional (default None). When None, the step behaves exactly as before (no embedding).
**Rationale:** Backward compatibility is a stated constraint. Plugins will pass the embeddings port when constructing the step.

### C3: Batch size for incremental embedding
**Question:** What batch_size should incremental embedding use?
**Answer:** Accept an optional `embed_batch_size` parameter defaulting to 50 (same as EmbedStep default).
**Rationale:** Consistency with existing defaults. Batch size can be tuned independently if needed.

### C4: Error handling for incremental embedding failures
**Question:** If embedding fails for a document's chunks after summarization succeeds, should the step continue?
**Answer:** Log the error, append to context.errors, leave chunks without embeddings. The global EmbedStep will attempt to embed them. Continue to next document.
**Rationale:** Graceful degradation. The existing EmbedStep already handles partially-embedded chunk lists.

### C5: Documents below chunk threshold
**Question:** Should documents below the chunk threshold (not summarized) have their chunks embedded eagerly in DocumentSummaryStep?
**Answer:** No. Only summarized documents get incremental embedding. Below-threshold documents are embedded by the global EmbedStep.
**Rationale:** The primary latency bottleneck is sequential summarization of large documents. Small documents don't benefit from this optimization.

### C6: Unchanged documents from change detection
**Question:** Should change-detected unchanged documents have their chunks embedded in DocumentSummaryStep?
**Answer:** No change needed. These are already skipped by DocumentSummaryStep's existing logic and already have pre-loaded embeddings.
**Rationale:** Existing filtering logic handles this correctly.
