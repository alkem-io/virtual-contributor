# Spec 019: Batched Ingest Pipeline Processing

**Status:** Draft
**Date:** 2026-04-15
**Author:** Valentin Yanakiev

## Problem Statement

The current ingest pipeline processes all documents sequentially through every step in a single pass. For large corpora (20+ documents), this creates two problems:

1. **All-or-nothing failure risk.** If a step fails late in the pipeline (e.g., StoreStep on batch 15 of 20), all prior LLM summarization work is discarded. With slow summarization models (2+ min/call), this can waste 40+ minutes of GPU time.

2. **Unbounded memory pressure.** All chunks from all documents are held in memory simultaneously throughout the pipeline. For large spaces with hundreds of documents, this can exhaust available memory.

The pipeline needs to process documents in configurable batches, persisting each batch before moving to the next, so that partial failures preserve completed work.

## User Scenarios

### US-019.1: Partial Failure Recovery (P1)

**As** an operator running a large website ingest,
**I want** each batch of documents to be persisted independently,
**so that** a failure in batch N does not discard the successfully stored results from batches 1..N-1.

**Acceptance Scenarios:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 10 documents, batch_size=5 | Batch 1 (docs 1-5) succeeds, batch 2 (docs 6-10) fails at EmbedStep | Chunks from docs 1-5 are persisted in the store; errors from batch 2 are reported in the result |
| 2 | 4 documents, batch_size=2 | All batches succeed | All chunks stored; result.success=True; no errors |
| 3 | 1 document, batch_size=5 | Processing succeeds | Single batch runs; result identical to sequential mode |

### US-019.2: Configurable Batch Size (P1)

**As** a platform administrator,
**I want** to configure the ingest batch size via the `INGEST_BATCH_SIZE` environment variable,
**so that** I can tune memory usage and failure blast radius for my deployment.

**Acceptance Scenarios:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `INGEST_BATCH_SIZE=3` and 7 documents | Ingest runs | 3 batches created: [3, 3, 1] documents |
| 2 | `INGEST_BATCH_SIZE=0` (invalid) | Plugin initializes | batch_size is clamped to 1 (minimum) |
| 3 | No env var set | Ingest runs | Default batch_size of 5 is used |

### US-019.3: Body-of-Knowledge Summary in Finalize Phase (P1)

**As** the system,
**I want** the BoK summary to run once after all batches complete,
**so that** it has access to all document summaries and raw chunk content across the entire corpus.

**Acceptance Scenarios:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 6 documents in 2 batches | Batched ingest completes | BoK summary receives all 6 document summaries in the finalize context |
| 2 | Finalize context | BoK step executes | raw_chunks_by_doc contains chunk content from all batches; chunks list is empty |
| 3 | BoK step generates summary | Finalize EmbedStep + StoreStep run | BoK summary is embedded and stored |

### US-019.4: Correct Change Detection Across Batches (P2)

**As** the system,
**I want** change detection in each batch to know about ALL document IDs in the full corpus,
**so that** documents outside the current batch are not falsely flagged as removed.

**Acceptance Scenarios:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | 10 docs in 2 batches, doc-A in batch 2 | Batch 1 runs ChangeDetection | doc-A is NOT in removed_document_ids (it exists in all_document_ids) |
| 2 | doc-X was in previous ingest but not in current corpus | Any batch runs ChangeDetection | doc-X IS in removed_document_ids |
| 3 | all_document_ids is empty (sequential mode fallback) | ChangeDetection runs | Falls back to current batch document IDs (backward-compatible behavior) |

### US-019.5: Backward Compatibility (P2)

**As** a developer,
**I want** the existing `IngestEngine(steps=[...])` API to work unchanged,
**so that** existing callers (cleanup pipelines, tests) are not broken.

**Acceptance Scenarios:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `IngestEngine(steps=[ChunkStep, EmbedStep, StoreStep])` | engine.run() called | Sequential execution identical to pre-batch behavior |
| 2 | `IngestEngine(steps=[...], batch_steps=[...])` | Constructor called | ValueError raised: cannot specify both |
| 3 | `IngestEngine(batch_steps=[...])` without finalize_steps | Constructor called | ValueError raised: finalize_steps required |

### US-019.6: Orphan Cleanup After All Batches (P2)

**As** the system,
**I want** OrphanCleanupStep to run once in the finalize phase with accumulated orphan IDs from all batches,
**so that** stale chunks are cleaned up correctly after all batches have persisted their data.

**Acceptance Scenarios:**

| # | Given | When | Then |
|---|-------|------|------|
| 1 | Batch 1 identifies orphans {A, B}, batch 2 identifies orphans {C} | Finalize OrphanCleanup runs | All three orphans (A, B, C) are deleted |
| 2 | A batch had errors | Finalize OrphanCleanup is destructive-gated | OrphanCleanup is skipped; no data loss |

## Functional Requirements

| ID | Requirement | Traces to |
|----|-------------|-----------|
| FR-001 | IngestEngine supports two modes: sequential (`steps=`) and batched (`batch_steps=` + `finalize_steps=` + `batch_size=`). | US-019.1, US-019.5 |
| FR-002 | In batched mode, documents are partitioned into batches of `batch_size` documents. Each batch runs `batch_steps` in order. | US-019.1, US-019.2 |
| FR-003 | After all batches complete, `finalize_steps` run once on an accumulated context. | US-019.3, US-019.6 |
| FR-004 | The finalize context receives: all documents, merged document_summaries, merged orphan_ids, merged removed/changed document IDs, accumulated counters (chunks_stored, chunks_skipped), accumulated errors, and raw_chunks_by_doc. | US-019.3 |
| FR-005 | The finalize context starts with an empty `chunks` list. Finalize steps (e.g., BoK) append their own chunks for embedding/storing. | US-019.3 |
| FR-006 | Each batch context receives `all_document_ids` (the full set of document IDs across the entire ingest). | US-019.4 |
| FR-007 | ChangeDetectionStep uses `all_document_ids` (when non-empty) instead of current-batch document IDs for removed-document detection. | US-019.4 |
| FR-008 | BodyOfKnowledgeSummaryStep uses `raw_chunks_by_doc` (when non-empty) for section content in finalize mode, falling back to `chunks` list for sequential mode. | US-019.3 |
| FR-009 | PipelineContext gains two new fields: `all_document_ids: set[str]` and `raw_chunks_by_doc: dict[str, list[str]]`. | FR-006, FR-008 |
| FR-010 | Config field `batch_size` is renamed to `ingest_batch_size` with default 5. | US-019.2 |
| FR-011 | `main.py` injects `ingest_batch_size` into plugin constructors via introspection. | US-019.2 |
| FR-012 | Both `ingest_website` and `ingest_space` plugins split their step lists into `batch_steps` and `finalize_steps`. | FR-001 |
| FR-013 | Batch step metrics are keyed with `{step_name}_batch_{index}` suffixes. | Observability |
| FR-014 | Constructor validation: cannot specify both `steps` and `batch_steps`; `finalize_steps` required with `batch_steps`; must specify either `steps` or `batch_steps`. | US-019.5 |
| FR-015 | `batch_size` is clamped to minimum 1 via `max(1, batch_size)`. | US-019.2 |

## Success Criteria

- All 22 new tests and 2 updated tests (24 total) pass, covering batch mechanics, context isolation, accumulation, and finalize behavior.
- Existing sequential-mode tests continue to pass without modification (backward compatibility).
- Plugin tests validate the `batch_steps`/`finalize_steps` constructor pattern.
- No false removed-document detections in batched change detection.
- BoK summary has access to all document content in finalize phase.

## Assumptions

- The batch_steps always include a StoreStep that persists chunks before the batch context is discarded, ensuring partial-failure recovery.
- All documents fit in memory simultaneously (batching reduces per-step memory, not total document memory).
- The finalize phase runs synchronously after all batches; there is no parallel batch execution.
- The `raw_chunks_by_doc` accumulator captures only `embedding_type="chunk"` content, not summary chunks.
- Cleanup pipelines (zero-document re-ingestion) continue to use the sequential `steps=` API.
