# Tasks 019: Batched Ingest Pipeline Processing

**Date:** 2026-04-15
**Status:** All tasks completed

## Phase 1: Core Engine (PipelineContext and IngestEngine)

### Story: Extend PipelineContext for batched execution

- [X] T-001: Add `all_document_ids: set[str]` field to PipelineContext dataclass with `field(default_factory=set)` default
- [X] T-002: Add `raw_chunks_by_doc: dict[str, list[str]]` field to PipelineContext dataclass with `field(default_factory=dict)` default

### Story: Implement batched execution mode in IngestEngine

- [X] T-003: Add `batch_steps`, `finalize_steps`, and `batch_size` parameters to IngestEngine constructor alongside existing `steps` parameter
- [X] T-004: Add constructor validation: reject both `steps` and `batch_steps`; reject `batch_steps` without `finalize_steps`; reject neither `steps` nor `batch_steps`
- [X] T-005: Clamp `batch_size` to minimum 1 via `max(1, batch_size)`
- [X] T-006: Extract `_run_steps(steps, context, metrics_suffix="")` helper from existing sequential execution code
- [X] T-007: Extract `_build_result(context, doc_count)` as static method shared between sequential and batched paths
- [X] T-008: Implement `_run_batched()` method: partition documents, run batch_steps per batch, accumulate results, run finalize_steps
- [X] T-009: In `_run_batched()`, compute `all_document_ids` from the full document list and set it on each batch context
- [X] T-010: In `_run_batched()`, accumulate `raw_chunks_by_doc` from each batch's chunks (embedding_type="chunk" only) after batch_steps complete
- [X] T-011: In `_run_batched()`, merge batch results into global accumulators: document_summaries, orphan_ids, removed_document_ids, changed_document_ids, unchanged_chunk_hashes, errors, metrics, counters
- [X] T-012: In `_run_batched()`, construct finalize context with accumulated state and empty chunks list
- [X] T-013: Apply `_batch_{index}` suffix to batch step metrics keys via `metrics_suffix` parameter
- [X] T-014: Update `run()` dispatch to call `_run_batched()` when `batch_steps` is set, else `_run_sequential()`
- [X] T-015: Rename `_run_sequential()` (formerly the inline code in `run()`) and wire to `_run_steps()` and `_build_result()`

## Phase 2: Step Adaptations

### Story: Adapt ChangeDetectionStep for batched mode

- [X] T-016: In `_detect()`, use `context.all_document_ids` (when non-empty) instead of `current_doc_ids` for removed-document detection
- [X] T-017: When `all_document_ids` is empty, fall back to `current_doc_ids` for backward compatibility with sequential mode

### Story: Adapt BodyOfKnowledgeSummaryStep for finalize mode

- [X] T-018: In `execute()`, add branch: when `context.raw_chunks_by_doc` is non-empty, use it for section content instead of extracting from `context.chunks`
- [X] T-019: Derive `seen_doc_ids` from `context.documents` list filtered by presence in `raw_chunks_by_doc` (preserves document ordering)
- [X] T-020: Maintain fallback to `context.chunks` extraction when `raw_chunks_by_doc` is empty (sequential mode)

## Phase 3: Configuration and Wiring

### Story: Rename and reconfigure batch size setting

- [X] T-021: In `core/config.py`, rename `batch_size: int = 20` to `ingest_batch_size: int = 5`

### Story: Wire batch size into plugin constructors

- [X] T-022: In `main.py`, add `ingest_batch_size` to the signature introspection injection block
- [X] T-023: In `IngestWebsitePlugin.__init__()`, add `ingest_batch_size: int = 5` keyword parameter with `max(1, ...)` clamping
- [X] T-024: In `IngestSpacePlugin.__init__()`, add `ingest_batch_size: int = 5` keyword parameter with `max(1, ...)` clamping

## Phase 4: Plugin Step List Restructuring

### Story: Split website plugin step list into batch/finalize phases

- [X] T-025: In `IngestWebsitePlugin.handle()`, build `batch_steps` list: ChunkStep, ContentHashStep, ChangeDetectionStep, (conditional) DocumentSummaryStep, EmbedStep, StoreStep
- [X] T-026: In `IngestWebsitePlugin.handle()`, build `finalize_steps` list: (conditional) BodyOfKnowledgeSummaryStep, EmbedStep, StoreStep, OrphanCleanupStep
- [X] T-027: Construct `IngestEngine(batch_steps=..., finalize_steps=..., batch_size=self._ingest_batch_size)`

### Story: Split space plugin step list into batch/finalize phases

- [X] T-028: In `IngestSpacePlugin.handle()`, build `batch_steps` list (same structure as website, with space-specific chunk_size=9000, chunk_overlap=500)
- [X] T-029: In `IngestSpacePlugin.handle()`, build `finalize_steps` list (same structure as website)
- [X] T-030: Construct `IngestEngine(batch_steps=..., finalize_steps=..., batch_size=self._ingest_batch_size)`

## Phase 5: Tests

### Story: Engine batched mode tests (TestIngestEngineBatched)

- [X] T-031: Test constructor rejects both `steps` and `batch_steps`
- [X] T-032: Test constructor requires `finalize_steps` with `batch_steps`
- [X] T-033: Test constructor requires either `steps` or `batch_steps`
- [X] T-034: Test batch step sequencing: batch_steps run per batch, finalize_steps run once
- [X] T-035: Test batch context isolation: each batch sees only its documents
- [X] T-036: Test all_document_ids propagated to every batch context
- [X] T-037: Test results accumulated across batches (counters, errors)
- [X] T-038: Test document_summaries accumulated from multiple batches into finalize context
- [X] T-039: Test raw_chunks_by_doc accumulated from batch chunks
- [X] T-040: Test finalize context starts with empty chunks list
- [X] T-041: Test finalize context has all original documents
- [X] T-042: Test metrics keyed with `_batch_{index}` suffix
- [X] T-043: Test error in one batch does not block subsequent batches
- [X] T-044: Test destructive finalize steps gated by batch errors
- [X] T-045: Test backward compat: `IngestEngine(steps=[...])` still works

### Story: Batched ChangeDetectionStep tests (TestChangeDetectionStepBatched)

- [X] T-046: Test no false removals when all_document_ids is set
- [X] T-047: Test fallback to current_doc_ids when all_document_ids is empty
- [X] T-048: Test actual removal detected with all_document_ids

### Story: Batched BoK summary tests (TestBoKSummaryStepBatchedMode)

- [X] T-049: Test BoK uses raw_chunks_by_doc when populated
- [X] T-050: Test BoK prefers document_summaries over raw chunks
- [X] T-051: Test BoK falls back to chunks when raw_chunks_by_doc is empty
- [X] T-052: Test empty corpus cleanup in batched mode

### Story: Plugin test updates

- [X] T-053: Update test_ingest_website.py assertions to verify `batch_steps`/`finalize_steps` kwargs on IngestEngine constructor
- [X] T-054: Update test_ingest_space.py assertions to verify `batch_steps`/`finalize_steps` kwargs on IngestEngine constructor
