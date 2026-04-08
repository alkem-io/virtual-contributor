# Tasks: Incremental Embedding -- Embed Documents as They Finish Summarization

**Story:** alkem-io/alkemio#1826
**Date:** 2026-04-08

## Task List (dependency-ordered)

### T1: Add optional `embeddings_port` and `embed_batch_size` to `DocumentSummaryStep.__init__`

**File:** `core/domain/pipeline/steps.py`
**Depends on:** none
**Acceptance criteria:**
- `DocumentSummaryStep` accepts optional `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50`.
- Stored as instance attributes `_embeddings` and `_embed_batch_size`.
- Existing constructor calls (without these args) continue to work.
**Test:** `test_no_embed_when_port_is_none` -- instantiate without embeddings_port, verify chunks have no embeddings after execute.

### T2: Implement per-document incremental embedding in `DocumentSummaryStep.execute`

**File:** `core/domain/pipeline/steps.py`
**Depends on:** T1
**Acceptance criteria:**
- After each document's summary is produced and appended to `context.chunks`, if `self._embeddings` is not None:
  1. Collect the document's content chunks where `embedding is None`.
  2. Collect the just-appended summary chunk.
  3. Embed all collected chunks in batches via `self._embeddings.embed()`.
  4. Assign embeddings to chunks.
- On embedding failure, append error to `context.errors` with prefix `DocumentSummaryStep`, and leave chunks unembedded.
**Tests:**
- `test_incremental_embed_after_summary`
- `test_incremental_embed_summary_chunk`
- `test_incremental_embed_skips_preloaded`
- `test_incremental_embed_error_recorded`
- `test_below_threshold_not_embedded_by_summary_step`

### T3: Update `ingest_space` plugin to pass `embeddings_port`

**File:** `plugins/ingest_space/plugin.py`
**Depends on:** T1
**Acceptance criteria:**
- `DocumentSummaryStep` constructor call includes `embeddings_port=self._embeddings`.
**Test:** Existing integration tests pass; no new test needed (plugin wiring is covered by existing test_ingest_space.py).

### T4: Update `ingest_website` plugin to pass `embeddings_port`

**File:** `plugins/ingest_website/plugin.py`
**Depends on:** T1
**Acceptance criteria:**
- `DocumentSummaryStep` constructor call includes `embeddings_port=self._embeddings`.
**Test:** Existing integration tests pass; no new test needed.

### T5: Write new unit tests for incremental embedding

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T2
**Acceptance criteria:**
- All tests from the Test Strategy in plan.md are implemented and pass.
- Tests use `MockEmbeddingsPort` and `MockLLMPort` from conftest.
**Tests:**
- `test_incremental_embed_after_summary`
- `test_incremental_embed_summary_chunk`
- `test_no_embed_when_port_is_none`
- `test_incremental_embed_skips_preloaded`
- `test_incremental_embed_error_recorded`
- `test_below_threshold_not_embedded_by_summary_step`

### T6: Write integration test for EmbedStep skip behavior

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T2, T5
**Acceptance criteria:**
- `test_embed_step_skips_incrementally_embedded`: Run DocumentSummaryStep with embeddings_port, then run EmbedStep. Verify EmbedStep's embeddings port receives zero calls for already-embedded chunks.
**Test:** `test_embed_step_skips_incrementally_embedded`

### T7: Verify all existing tests pass

**Depends on:** T1-T6
**Acceptance criteria:**
- `poetry run pytest` passes with zero failures.
- `poetry run ruff check core/ plugins/ tests/` passes.
- `poetry run pyright core/ plugins/` passes.
