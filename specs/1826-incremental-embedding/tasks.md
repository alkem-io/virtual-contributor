# Tasks: Incremental Embedding

**Story:** alkem-io/alkemio#1826
**Date:** 2026-04-08

## Task List (dependency-ordered)

### T1: Add embeddings_port and embed_batch_size to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Dependencies:** None
**Description:** Extend `DocumentSummaryStep.__init__` to accept optional `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50` parameters. Store them as instance attributes.
**Acceptance criteria:**
- Constructor accepts the new parameters.
- Default values are `None` and `50` respectively.
- Existing constructor calls without these parameters continue to work.
**Test:** Existing `TestDocumentSummaryStep` tests pass unchanged (they don't pass the new params).

### T2: Implement per-document incremental embedding in DocumentSummaryStep.execute

**File:** `core/domain/pipeline/steps.py`
**Dependencies:** T1
**Description:** After each document's summary is produced (after `context.chunks.append(Chunk(content=summary, ...))` on line 305-307), if `self._embeddings` is set:
1. Collect the document's content chunks (from `chunks_by_doc`) that have `embedding is None`.
2. Include the newly appended summary chunk.
3. Embed them in batches of `self._embed_batch_size` using `self._embeddings.embed(texts)`.
4. On error: log warning, append to `context.errors`, leave chunks without embeddings.
5. Log the number of chunks embedded for each document.

**Acceptance criteria:**
- After each document summary, that document's unembedded content chunks and summary chunk have embeddings set.
- When embeddings_port is None, no embedding occurs (existing behavior preserved).
- Errors during embedding are logged and recorded in context.errors but do not prevent summarization of remaining documents.
**Tests:** T4 (unit tests for incremental embedding).

### T3: Update plugin pipelines to pass embeddings_port

**Files:** `plugins/ingest_space/plugin.py`, `plugins/ingest_website/plugin.py`
**Dependencies:** T1
**Description:** In both plugins' `handle` method, pass `embeddings_port=self._embeddings` to the `DocumentSummaryStep` constructor.
**Acceptance criteria:**
- `DocumentSummaryStep` in both plugins receives the embeddings port.
- Pipeline still includes the global `EmbedStep` as a catch-all.
**Tests:** Existing plugin tests pass. T5 (integration test).

### T4: Write unit tests for incremental embedding

**File:** `tests/core/domain/test_pipeline_steps.py`
**Dependencies:** T2
**Description:** Add tests to `TestDocumentSummaryStep`:
1. `test_incremental_embedding_embeds_chunks_after_summary` -- with embeddings_port, verify content chunks and summary chunk have embeddings after execute.
2. `test_no_incremental_embedding_without_port` -- without embeddings_port, verify chunks lack embeddings (existing behavior confirmation).
3. `test_incremental_embedding_error_resilience` -- failing embeddings_port, verify summarization succeeds, error recorded, chunks lack embeddings.
4. `test_incremental_embedding_skipped_by_embed_step` -- run DocumentSummaryStep with embeddings_port, then EmbedStep. Verify EmbedStep only embeds chunks not already embedded.
**Acceptance criteria:**
- All four tests pass.
- Tests use existing MockEmbeddingsPort and MockLLMPort from conftest.
**Tests:** Self-verifying.

### T5: Write integration test for full pipeline with incremental embedding

**File:** `tests/core/domain/test_pipeline_steps.py`
**Dependencies:** T2, T3, T4
**Description:** Add an integration test to `TestIngestEngine`:
- `test_incremental_embedding_full_pipeline` -- construct a full pipeline (ChunkStep, ContentHashStep, DocumentSummaryStep with embeddings_port, BodyOfKnowledgeSummaryStep, EmbedStep, StoreStep). Run with multiple documents. Verify all chunks are stored with embeddings.
**Acceptance criteria:**
- Test passes.
- All chunks (content + summaries + BoK) have embeddings.
- EmbedStep only embeds chunks not already embedded by DocumentSummaryStep.
**Tests:** Self-verifying.
