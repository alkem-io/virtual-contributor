# Clarifications: Handle Empty Corpus Re-ingestion

**Story:** #35
**Iteration:** 1

---

## Clarification 1: Should the cleanup pipeline include summary cleanup?

**Ambiguity:** The story says to run ChangeDetectionStep + OrphanCleanupStep. OrphanCleanupStep already handles deleting chunks for `removed_document_ids` including their `-summary` entries. But should we also delete the `body-of-knowledge-summary` entry?

**Chosen Answer:** Yes. When all documents are removed, the BoK summary is also stale. The OrphanCleanupStep deletes by `documentId` from `removed_document_ids`, which will catch per-document summaries. For the BoK-level summary (`body-of-knowledge-summary`), the ChangeDetectionStep will flag it via the orphan detection mechanism since its documentId won't appear in the (empty) current document set. Actually, ChangeDetectionStep only looks at chunks with `embeddingType == "chunk"` for current_doc_ids, and the BoK summary has `embeddingType == "summary"`. The OrphanCleanupStep deletes by documentId for removed documents, plus orphan IDs. The BoK summary won't be caught by either mechanism since it has a special documentId `body-of-knowledge-summary` that's never in the incoming document list. However, the ChangeDetectionStep compares `existing_doc_ids` (from stored chunks with `embeddingType == "chunk"`) against `current_doc_ids` (from incoming chunks). All existing doc IDs will be in `removed_document_ids`. OrphanCleanupStep then deletes both the document's chunks and its `-summary` entry for each removed doc. The BoK summary itself (`body-of-knowledge-summary`) is NOT deleted. This is acceptable -- on the next non-empty ingestion, it will be regenerated. For a truly empty corpus, the BoK summary will be the only remaining entry, which is inert (it won't affect RAG retrieval meaningfully since the expert plugin queries by content, not by summary type).

**Rationale:** Keeping the minimal pipeline (ChangeDetection + OrphanCleanup) consistent with the story's proposed approach. The BoK summary edge case is minor and does not affect correctness of RAG results.

## Clarification 2: What return value for IngestWebsitePlugin on empty cleanup?

**Ambiguity:** The current early-return for IngestWebsitePlugin returns `IngestionResult.SUCCESS` with `error="No content extracted"`. Should the cleanup path also set this error message?

**Chosen Answer:** No. The cleanup path should return a clean success with no error message when cleanup succeeds, since the pipeline ran successfully. The current "No content extracted" message was an informational note for the early-return case; with cleanup now running, the result reflects the pipeline outcome. If the pipeline errors, those errors propagate normally.

**Rationale:** Aligns with IngestSpacePlugin behavior and IngestEngine contract -- success/failure is determined by whether `result.errors` is empty.

## Clarification 3: Should the IngestWebsitePlugin distinguish crawl failure from empty-but-successful?

**Ambiguity:** The current code has `crawl()` returning an empty list on connection errors (it catches exceptions internally). The story says "distinguish fetch succeeded, empty result from fetch failed." But crawl already returns `[]` on failure, making it indistinguishable from "no pages found."

**Chosen Answer:** The crawl function already handles errors internally and returns `[]` for both "no pages" and "crawl error." Since both cases result in zero documents after extraction, the cleanup pipeline should run in both scenarios. The `crawl()` function logs errors internally. The only true "fetch failure" for the website plugin would be an unhandled exception propagating from `crawl()`, which is already caught by the outer try/except. So the current distinction is: exception = failure (no cleanup), empty list = cleanup.

**Rationale:** The crawl function's error handling already provides the distinction. An empty return from crawl means the fetch completed (even if some pages failed), so cleanup is appropriate.

## Clarification 4: Collection name derivation for the cleanup pipeline

**Ambiguity:** Both plugins derive collection_name before the fetch. Is this guaranteed to be correct for the cleanup path?

**Chosen Answer:** Yes. The collection name derivation happens before the fetch in both plugins and uses event data (bok_id + purpose for space, netloc for website). This is the same collection the cleanup needs to target.

**Rationale:** No change needed -- the collection name is already computed before the branch point.

## Clarification 5: Should the cleanup pipeline log distinctively?

**Ambiguity:** Should there be logging to indicate that an empty-corpus cleanup is happening vs. a normal ingestion?

**Chosen Answer:** Yes. Add an info-level log message in both plugins indicating that the empty document list triggered a cleanup-only pipeline run. This aids debugging.

**Rationale:** Observability is important for production diagnosis.
