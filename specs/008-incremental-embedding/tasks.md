# Tasks: Incremental Embedding After Summarization

**Story:** alkem-io/alkemio#1826
**Created:** 2026-04-08

## Task Dependency Order

```
T1 --> T2 --> T3 --> T4 --> T5
```

## T1: Add embeddings_port parameter and _embed_document_chunks helper to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`

**Changes:**
1. Add `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50` to `DocumentSummaryStep.__init__`.
2. Add private `_embed_document_chunks(self, chunks, context, doc_id)` method that:
   - Filters chunks to those with `embedding is None`.
   - Batches by `self._embed_batch_size`.
   - Calls `self._embeddings.embed(texts)` for each batch.
   - Assigns embeddings to chunks.
   - On error, appends `"DocumentSummaryStep: embedding failed for {doc_id}: {exc}"` to context.errors.
3. After each document summary loop iteration (after creating summary chunk and appending to context), if `self._embeddings is not None`, call `_embed_document_chunks` with the document's content chunks plus the newly created summary chunk.

**Acceptance Criteria:**
- DocumentSummaryStep accepts optional embeddings_port.
- When provided, chunks for each summarized document are embedded immediately after summary.
- When not provided, behavior is identical to current.

**Tests:** T3 covers this.

## T2: Update plugin pipeline assemblies to pass embeddings_port

**Files:** `plugins/ingest_space/plugin.py`, `plugins/ingest_website/plugin.py`

**Changes:**
1. In `IngestSpacePlugin.handle`, add `embeddings_port=self._embeddings` to the `DocumentSummaryStep(...)` constructor call.
2. In `IngestWebsitePlugin.handle`, add `embeddings_port=self._embeddings` to the `DocumentSummaryStep(...)` constructor call.

**Acceptance Criteria:**
- Both ingest plugins pass their embeddings port to DocumentSummaryStep.
- Pipeline step order is unchanged.
- EmbedStep remains in the pipeline to handle any remaining un-embedded chunks.

**Tests:** Existing plugin tests, plus T3 unit tests.

## T3: Write unit tests for incremental embedding behavior

**File:** `tests/core/domain/test_pipeline_steps.py`

**Tests to add in `TestDocumentSummaryStep`:**
1. `test_incremental_embedding_after_summary` -- With embeddings_port, all chunks for a summarized document have embeddings after execute.
2. `test_summary_chunk_gets_embedded` -- The summary chunk produced for the document also has an embedding.
3. `test_unchanged_chunks_not_re_embedded` -- Chunks with pre-existing embeddings are not sent to the embeddings port.
4. `test_no_embedding_without_port` -- Without embeddings_port (None), chunks remain without embeddings after DocumentSummaryStep.
5. `test_embedding_error_does_not_block_summary` -- If embedding raises, the summary still exists and errors are recorded but no exception propagates.

**Acceptance Criteria:**
- All five tests pass.
- Tests use MockEmbeddingsPort from conftest.

## T4: Verify existing tests pass

**Command:** `poetry run pytest`

**Acceptance Criteria:**
- All existing tests pass without modification.
- No regressions in EmbedStep, StoreStep, ChangeDetectionStep, or IngestEngine tests.

## T5: Lint, type-check, build verification

**Commands:**
- `poetry run ruff check core/ plugins/ tests/`
- `poetry run pyright core/ plugins/`

**Acceptance Criteria:**
- Zero ruff violations.
- Zero pyright errors.
