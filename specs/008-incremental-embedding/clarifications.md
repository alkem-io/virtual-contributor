# Clarifications

**Iteration count:** 1

## Clarification 1: Should DocumentSummaryStep embed ALL of a document's chunks, or only the changed ones?

**Question:** When DocumentSummaryStep finishes summarizing a document, should it embed all chunks for that document, or only those without a pre-existing embedding (from change detection)?

**Resolution:** Only embed chunks that do not already have an embedding (`chunk.embedding is None`). This is consistent with how EmbedStep already works and respects the change detection optimization that pre-loads embeddings for unchanged chunks.

**Rationale:** Unchanged chunks already have their embeddings pre-loaded by ChangeDetectionStep. Re-embedding them would waste GPU resources and contradict the deduplication design (ADR-006).

## Clarification 2: Should the embeddings_port parameter be required or optional in DocumentSummaryStep?

**Question:** Should `embeddings_port` be a required constructor parameter, or optional (defaulting to None for backward compatibility)?

**Resolution:** Optional, defaulting to `None`. When `None`, DocumentSummaryStep behaves exactly as before (no incremental embedding). When provided, it performs incremental embedding after each document's summary.

**Rationale:** This preserves backward compatibility. Any existing code that constructs DocumentSummaryStep without an embeddings_port continues to work. The parameter is only used when explicitly passed by the plugin pipeline assembly.

## Clarification 3: Should the summary chunk itself be embedded incrementally?

**Question:** After DocumentSummaryStep creates a summary chunk for a document, should that summary chunk also be embedded immediately, or left for EmbedStep?

**Resolution:** Yes, embed the summary chunk immediately as well. Since we already have the embeddings port available and the summary chunk is freshly created, embedding it right away avoids leaving it for EmbedStep and maximizes the overlap benefit.

**Rationale:** The summary chunk is produced at the same time as the document's content chunks are ready for embedding. Embedding it together with the content chunks (or right after) is a natural extension and avoids any gap.

## Clarification 4: What batch_size should DocumentSummaryStep use for embedding?

**Question:** EmbedStep uses a configurable `batch_size` (default 50). Should DocumentSummaryStep use the same batch size, or a different default?

**Resolution:** Use the same default of 50, exposed as an `embed_batch_size` constructor parameter for consistency. In practice, a single document's chunks will typically be fewer than 50, so most documents will be embedded in a single batch call.

**Rationale:** Consistency with EmbedStep defaults. The batch_size controls API call granularity to the embedding service; same default makes behavior predictable.

## Clarification 5: How should embedding errors within DocumentSummaryStep be reported?

**Question:** If embedding fails for a document's chunks during DocumentSummaryStep, should it be reported as a DocumentSummaryStep error or an EmbedStep error?

**Resolution:** Report as a DocumentSummaryStep error with a clear prefix indicating it was the embedding sub-operation that failed, e.g., `"DocumentSummaryStep: embedding failed for {doc_id}: {exc}"`. The summarization itself succeeded; only the incremental embedding failed. EmbedStep will still attempt to embed any chunks left without embeddings.

**Rationale:** The error originates within DocumentSummaryStep's execute method, so attributing it there is accurate. EmbedStep's fallback behavior (embed chunks without embeddings) provides resilience.

## Clarification 6: Should documents below the chunk_threshold also get their chunks embedded incrementally?

**Question:** Documents with fewer chunks than `chunk_threshold` are not summarized. Should their chunks be embedded during DocumentSummaryStep anyway?

**Resolution:** No. Documents below the threshold are not processed by DocumentSummaryStep at all. Their chunks will be embedded by EmbedStep as before.

**Rationale:** The purpose of incremental embedding is to overlap with summarization I/O. Documents that are not summarized have no summarization I/O to overlap with, so there is no benefit. Keeping DocumentSummaryStep focused on its core responsibility (summarize + embed summarized documents) is cleaner.
