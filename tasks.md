# Tasks: Incremental Embedding

**Story:** #1826

## Task List (dependency-ordered)

### T1: Add inline embedding to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Dependencies:** None
**Description:** Extend `DocumentSummaryStep.__init__` to accept optional `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50`. After each document's summary is produced and appended to context, embed all of that document's content chunks plus the new summary chunk using `_embed_document_chunks()`. Skip chunks that already have embeddings (from ChangeDetectionStep). Capture per-document embedding errors in `context.errors` without halting.
**Acceptance Criteria:**
- Constructor accepts `embeddings_port` (default None) and `embed_batch_size` (default 50).
- When `embeddings_port` is provided, chunks are embedded inline after each document summary.
- When `embeddings_port` is None, behavior is identical to current implementation.
- Per-document embedding errors are captured in context.errors.
**Tests:** T4.1, T4.2, T4.3, T4.4

### T2: Update ingest_space plugin

**File:** `plugins/ingest_space/plugin.py`
**Dependencies:** T1
**Description:** Pass `self._embeddings` to `DocumentSummaryStep` as `embeddings_port` in the pipeline construction.
**Acceptance Criteria:**
- `DocumentSummaryStep` receives the embeddings port.
- Pipeline step order remains: Chunk -> ContentHash -> ChangeDetection -> DocumentSummary(+embed) -> BoKSummary -> Embed(safety net) -> Store -> OrphanCleanup.
**Tests:** Existing plugin integration tests remain green.

### T3: Update ingest_website plugin

**File:** `plugins/ingest_website/plugin.py`
**Dependencies:** T1
**Description:** Pass `self._embeddings` to `DocumentSummaryStep` as `embeddings_port` in the pipeline construction.
**Acceptance Criteria:**
- `DocumentSummaryStep` receives the embeddings port.
- Pipeline step order remains consistent with ingest_space.
**Tests:** Existing plugin integration tests remain green.

### T4: Add and update unit tests

**File:** `tests/core/domain/test_pipeline_steps.py`
**Dependencies:** T1
**Description:** Add new tests and update existing ones for the incremental embedding behavior.

**T4.1: test_inline_embedding_after_summary**
- Construct `DocumentSummaryStep` with `MockEmbeddingsPort`.
- Execute on context with > chunk_threshold chunks.
- Assert all content chunks AND the summary chunk have embeddings after execute.

**T4.2: test_embed_step_skips_already_embedded**
- Run `DocumentSummaryStep` with inline embedding, then run `EmbedStep`.
- Assert `EmbedStep` makes zero embed calls for already-embedded chunks.

**T4.3: test_inline_embed_error_handling**
- Provide a failing embeddings port.
- Assert errors are captured in context.errors.
- Assert summarization still completes (summary chunk is created).

**T4.4: test_no_embeddings_port_backward_compat**
- Construct `DocumentSummaryStep` without embeddings_port.
- Assert chunks have no embeddings after execute (same as before).

**T4.5: test_below_threshold_not_embedded_inline**
- Documents with <= chunk_threshold chunks should NOT be embedded by DocumentSummaryStep.

**T4.6: test_full_pipeline_with_incremental_embedding**
- Integration test: Chunk -> ContentHash -> DocumentSummary(+embed) -> BoKSummary -> Embed -> Store.
- Assert all chunks are stored with embeddings.

**Acceptance Criteria:**
- All new tests pass.
- All existing tests pass (update constructor calls if needed).
