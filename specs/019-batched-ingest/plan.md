# Plan 019: Batched Ingest Pipeline Processing

**Date:** 2026-04-15

## Summary

Refactor the ingest pipeline from a single-pass sequential model to a document-level batched approach. Documents are processed in configurable batches through `batch_steps` (Chunk -> Hash -> ChangeDetection -> Summarize -> Embed -> Store), with each batch persisted before the next begins. After all batches complete, `finalize_steps` (BoK Summary -> Embed -> Store -> OrphanCleanup) run once on accumulated cross-batch state. The existing `steps=` API is preserved for backward compatibility.

## Technical Context

The pipeline engine (`core/domain/pipeline/engine.py`) currently runs an ordered list of `PipelineStep` instances against a single `PipelineContext` containing all documents. This works for small corpora but creates two problems at scale:

1. **Failure blast radius**: A late-stage failure (e.g., StoreStep batch error) discards all prior summarization work. With slow LLM models, this can waste 40+ minutes of GPU/API cost.

2. **BoK generation**: The Body-of-Knowledge summary needs content from all documents, but in batched mode, each batch's chunks are discarded after storage. A new accumulation strategy is needed to feed raw chunk content to the finalize phase.

The solution introduces a two-phase execution model within IngestEngine while keeping the `PipelineStep` protocol unchanged.

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| P1: AI-Native Development | PASS | No interactive steps; batching is fully autonomous |
| P2: SOLID Architecture | PASS | Engine API backward-compatible (Open/Closed); plugins depend on ports, not adapters (Dependency Inversion) |
| P3: No Vendor Lock-in | N/A | No provider-specific changes |
| P4: Optimised Feedback Loops | PASS | 22 new + 2 updated tests covering batch mechanics, context isolation, error gating |
| P5: Best Available Infrastructure | N/A | No CI/CD changes |
| P6: Spec-Driven Development | PASS | Full SDD artifact set |
| P7: No Filling Tests | PASS | Every test verifies real batch behavior — isolation, accumulation, destructive gating, backward compat |
| P8: Architecture Decision Records | N/A | No port/contract/dependency changes; engine API change is additive |
| AS: Microkernel | PASS | Changes in core domain, not plugin-specific logic |
| AS: Hexagonal | PASS | No adapter or port interface changes |
| AS: Plugin Contract | PASS | Plugin contract unchanged; plugins use new engine API via constructor kwargs |
| AS: Async-First | PASS | All batch processing is async; no blocking calls introduced |
| AS: Simplicity | PASS | Minimal new fields (2 on PipelineContext), no speculative abstractions |

## Project Structure

### Files Changed

| File | Change Type | Description |
|------|-------------|-------------|
| `core/domain/pipeline/engine.py` | Modified | PipelineContext gains `all_document_ids` and `raw_chunks_by_doc` fields. IngestEngine gains `batch_steps`/`finalize_steps` constructor, `_run_batched()` method, `_run_steps()` helper, `_build_result()` static method. |
| `core/domain/pipeline/steps.py` | Modified | ChangeDetectionStep._detect() uses `all_document_ids` for removed-doc detection. BodyOfKnowledgeSummaryStep.execute() supports `raw_chunks_by_doc` for finalize context. |
| `core/config.py` | Modified | Rename `batch_size` -> `ingest_batch_size`, default changed from 20 to 5. |
| `main.py` | Modified | Add `ingest_batch_size` injection into plugin constructors via signature introspection. |
| `plugins/ingest_website/plugin.py` | Modified | Split step list into `batch_steps` and `finalize_steps`. Add `ingest_batch_size` constructor parameter. |
| `plugins/ingest_space/plugin.py` | Modified | Same structural change as website plugin. |
| `tests/core/domain/test_pipeline_steps.py` | Modified | 22 new tests: TestIngestEngineBatched (13), TestChangeDetectionStepBatched (3), TestBoKSummaryStepBatchedMode (4), plus 2 updated tests. |
| `tests/plugins/test_ingest_website.py` | Modified | Updated assertions for `batch_steps`/`finalize_steps` kwargs. |
| `tests/plugins/test_ingest_space.py` | Modified | Same. |

### Architecture Diagram

```
Documents [d0, d1, d2, d3, d4, d5, d6]
                    |
            batch_size = 3
                    |
     +--------------+--------------+
     |              |              |
  Batch 0       Batch 1       Batch 2
  [d0,d1,d2]   [d3,d4,d5]    [d6]
     |              |              |
  batch_steps    batch_steps    batch_steps
  (Chunk->Hash   (Chunk->Hash   (Chunk->Hash
   ->Change->     ->Change->     ->Change->
   Summarize->    Summarize->    Summarize->
   Embed->Store)  Embed->Store)  Embed->Store)
     |              |              |
     +-- accumulate results -------+
                    |
            Finalize Context
            (all docs, merged summaries,
             raw_chunks_by_doc, orphan_ids)
                    |
            finalize_steps
            (BoK->Embed->Store->OrphanCleanup)
                    |
              IngestResult
```
