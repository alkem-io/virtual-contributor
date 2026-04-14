# Tasks: Incremental Embedding

**Input**: Design documents from `specs/017-incremental-embedding/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Single user story — tasks grouped by dependency phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1)
- Include exact file paths in descriptions

---

## Phase 1: Core Implementation (DocumentSummaryStep)

**Purpose**: Add inline embedding capability to `DocumentSummaryStep`.

- [X] T001 [US1] Add `embeddings_port: EmbeddingsPort | None = None` and `embed_batch_size: int = 50` parameters to `DocumentSummaryStep.__init__` in core/domain/pipeline/steps.py
- [X] T002 [US1] Implement `_embed_document_chunks()` private async method on `DocumentSummaryStep` in core/domain/pipeline/steps.py: embed chunks in batches, skip already-embedded chunks, capture errors in context.errors
- [X] T003 [US1] Wire inline embedding in `DocumentSummaryStep.execute()` in core/domain/pipeline/steps.py: after each document's summary chunk is created, call `_embed_document_chunks()` with content chunks + summary chunk when `embeddings_port` is not None

**Checkpoint**: `DocumentSummaryStep` supports inline embedding when constructed with an `embeddings_port`.

---

## Phase 2: Plugin Wiring

**Purpose**: Pass embeddings port from ingest plugins to `DocumentSummaryStep`.

- [X] T004 [P] [US1] Update `IngestSpacePlugin` in plugins/ingest_space/plugin.py: pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` constructor
- [X] T005 [P] [US1] Update `IngestWebsitePlugin` in plugins/ingest_website/plugin.py: pass `embeddings_port=self._embeddings` to `DocumentSummaryStep` constructor

**Checkpoint**: Both ingest plugins use incremental embedding. Pipeline step order: Chunk -> ContentHash -> ChangeDetection -> DocumentSummary(+embed) -> BoKSummary -> Embed(safety net) -> Store -> OrphanCleanup.

---

## Phase 3: Tests

**Purpose**: Verify all incremental embedding behaviors with unit tests.

- [X] T006 [P] [US1] test_inline_embedding_after_summary in tests/core/domain/test_pipeline_steps.py: construct `DocumentSummaryStep` with `MockEmbeddingsPort`, execute on context with > chunk_threshold chunks, assert all content chunks AND summary chunk have embeddings
- [X] T007 [P] [US1] test_embed_step_skips_already_embedded in tests/core/domain/test_pipeline_steps.py: run `DocumentSummaryStep` with inline embedding then `EmbedStep`, assert `EmbedStep` makes zero embed calls
- [X] T008 [P] [US1] test_inline_embed_error_handling in tests/core/domain/test_pipeline_steps.py: provide failing embeddings port, assert errors captured in context.errors, assert summary still produced
- [X] T009 [P] [US1] test_no_embeddings_port_backward_compat in tests/core/domain/test_pipeline_steps.py: construct without embeddings_port, assert chunks have no embeddings after execute
- [X] T010 [P] [US1] test_below_threshold_not_embedded_inline in tests/core/domain/test_pipeline_steps.py: document with <= chunk_threshold chunks should not be embedded by `DocumentSummaryStep`
- [X] T011 [P] [US1] test_full_pipeline_with_incremental_embedding in tests/core/domain/test_pipeline_steps.py: integration test running Chunk -> ContentHash -> DocumentSummary(+embed) -> BoKSummary -> Embed -> Store, assert all chunks stored with embeddings

**Checkpoint**: All incremental embedding behaviors verified.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Core)**: No dependencies — start immediately
- **Phase 2 (Plugin Wiring)**: Depends on Phase 1 (T001-T003)
- **Phase 3 (Tests)**: Depends on Phase 1 (T001-T003). Independent of Phase 2

### Parallel Opportunities

**Phase 1**: T001, T002, T003 are sequential (same file, dependent logic).
**Phase 2**: T004, T005 are parallel (different plugin files).
**Phase 3**: T006-T011 are all parallel (independent test functions in same file).

---

## Implementation Strategy

### MVP First

1. Complete Phase 1: Core `DocumentSummaryStep` changes
2. Complete Phase 2: Plugin wiring
3. **STOP and VALIDATE**: Run existing tests to verify backward compatibility
4. Complete Phase 3: Add new tests
5. All tests green — feature complete

### Incremental Delivery

1. Phase 1 -> `DocumentSummaryStep` gains inline embedding (backward compatible)
2. Phase 2 -> Both plugins use it (inline embedding active)
3. Phase 3 -> Full test coverage confirms all behaviors
