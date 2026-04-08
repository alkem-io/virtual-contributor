# Tasks: Incremental Embedding

**Story:** alkem-io/alkemio#1826

---

## Task List

### T1: Add incremental embedding to DocumentSummaryStep

**File:** `core/domain/pipeline/steps.py`
**Depends on:** None
**Acceptance criteria:**
- `DocumentSummaryStep.__init__` accepts `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50`.
- A new private method `_embed_chunks` embeds a list of chunks in batches, appending errors to context.
- In `execute()`, after each document's summary is produced, all of that document's content chunks (that lack embeddings) plus the new summary chunk are embedded immediately.
- When `embeddings_port is None`, no embedding occurs (backward compatibility).
- Errors during embedding are appended to `context.errors` with `DocumentSummaryStep(embed):` prefix and do not abort the loop.

**Tests proving done:** T-IE-1, T-IE-2, T-IE-3, T-IE-5, T-IE-6

---

### T2: Update ingest_space plugin to pass embeddings_port

**File:** `plugins/ingest_space/plugin.py`
**Depends on:** T1
**Acceptance criteria:**
- `DocumentSummaryStep` constructor call includes `embeddings_port=self._embeddings`.

**Tests proving done:** Code inspection, T-IE-7 (integration)

---

### T3: Update ingest_website plugin to pass embeddings_port

**File:** `plugins/ingest_website/plugin.py`
**Depends on:** T1
**Acceptance criteria:**
- `DocumentSummaryStep` constructor call includes `embeddings_port=self._embeddings`.

**Tests proving done:** Code inspection, T-IE-7 (integration)

---

### T4: Write unit tests for incremental embedding

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- T-IE-1: With embeddings_port, content chunks have embeddings after DocumentSummaryStep.
- T-IE-2: Summary chunk has embedding after DocumentSummaryStep.
- T-IE-3: Without embeddings_port (None), no embeddings set -- backward compat.
- T-IE-5: Embedding failure on one document does not block next document.
- T-IE-6: Below-threshold documents' chunks have no embeddings after DocumentSummaryStep.

**Tests proving done:** All listed tests pass.

---

### T5: Write integration test for full pipeline with incremental embedding

**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1, T4
**Acceptance criteria:**
- T-IE-7: Full pipeline (Chunk -> ContentHash -> ChangeDetection -> DocumentSummary(with embed) -> BoKSummary -> Embed -> Store) produces correct results. EmbedStep makes zero calls for already-embedded chunks. Store receives all chunks with embeddings.

**Tests proving done:** T-IE-7 passes.

---

### T6: Verify exit gates

**Depends on:** T1, T2, T3, T4, T5
**Acceptance criteria:**
- `poetry run pytest` -- all tests pass.
- `poetry run ruff check core/ plugins/ tests/` -- clean.
- `poetry run pyright core/ plugins/` -- clean.
