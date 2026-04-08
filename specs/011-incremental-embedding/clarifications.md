# Clarifications -- Incremental Embedding

## Iteration 1

| # | Ambiguity | Chosen Resolution | Rationale |
|---|-----------|-------------------|-----------|
| C-1 | Should the summary chunk produced per document also be embedded immediately, or only the content chunks? | Embed both content chunks AND the summary chunk immediately after each document's summary completes. | The summary chunk is ready at the same time; deferring it to EmbedStep adds no benefit and complicates the "already embedded" bookkeeping. |
| C-2 | Should `DocumentSummaryStep` use the same `batch_size` parameter as `EmbedStep` for embedding? | Yes, accept an optional `embed_batch_size` parameter (default 50) matching EmbedStep's default. | Consistency with EmbedStep behavior. A single document typically has 5-50 chunks, so 50 is a safe single-batch default. |
| C-3 | What happens when `embeddings_port` is None (backward compat)? Should the step raise, warn, or silently skip embedding? | Silently skip incremental embedding; behave exactly as current code. No warning needed. | This is the backward-compatibility path. The trailing EmbedStep handles all embedding in that case. |
| C-4 | How should embedding errors during DocumentSummaryStep be reported? Via `context.errors` like other steps, or silently? | Append to `context.errors` with prefix `DocumentSummaryStep(embed)` so operators can distinguish summarization errors from embedding errors. | Consistent with existing error reporting pattern. Does not abort the summarization loop. |
| C-5 | The issue mentions Option A "per-document embed after summary." Should we also embed the BoK summary chunk inside BodyOfKnowledgeSummaryStep? | No. The BoK summary is a single chunk produced at the end. The trailing EmbedStep handles it. Adding embed logic to BodyOfKnowledgeSummaryStep would violate single-responsibility with minimal benefit. | BoK summary is one chunk; the overhead of a separate embed call vs batch in EmbedStep is negligible. Keeps the change focused. |
| C-6 | Should we embed chunks for documents that are unchanged (change_detection preloaded their embeddings)? | No. The existing logic in DocumentSummaryStep already skips unchanged documents. Incremental embedding only runs for documents that are actually summarized. | Unchanged chunks already have embeddings from ChangeDetectionStep; re-embedding would waste resources. |
| C-7 | The `DocumentSummaryStep` currently processes documents sequentially in a for loop. Should incremental embedding happen inside that same loop iteration? | Yes. After `_refine_summarize` completes for a document, embed that document's chunks plus its summary chunk in the same iteration, before moving to the next document. | This is the simplest implementation of Option A. It overlaps the embedding I/O of doc N with the LLM start-up of doc N+1 at the async level. |

## Iteration 2

No new ambiguities found. All questions from Iteration 1 are resolved. Clean pass.
