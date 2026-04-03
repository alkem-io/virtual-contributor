# Implementation Plan: Composable Ingest Pipeline Engine

**Branch**: `004-pipeline-engine-redesign` | **Date**: 2026-04-02 | **Updated**: 2026-04-03 | **Status**: Implemented | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-pipeline-engine-redesign/spec.md`

## Summary

Replace the monolithic `run_ingest_pipeline()` function with a composable `IngestEngine` that executes independently testable `PipelineStep` instances in sequence. Fix the critical correctness bug where document summaries overwrite chunk embeddings — raw chunk content must always be stored separately, with summaries as additional entries. Restore body-of-knowledge overview summaries and rich summarization prompts lost during the original migration.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langgraph ^1.0.4, pydantic ^2.11, httpx ^0.27.2, aio-pika 9.5.7, chromadb-client ^1.5.0, beautifulsoup4 ^4.14
**Storage**: ChromaDB (vector store via HTTP client)
**Testing**: pytest (ruff for linting, pyright for type checking)
**Target Platform**: Linux server (Docker container, single image)
**Project Type**: Background service (message-driven worker)
**Performance Goals**: N/A — throughput bound by external LLM and embedding services
**Constraints**: Async-first (aio-pika prefetch=1), semaphore-limited LLM concurrency (default 8), batch processing for embeddings and storage (default 50)
**Scale/Scope**: 10-100 documents per ingestion invocation, 1-20 pages per website crawl

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Design Check

| Principle / Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Steps independently testable, pipeline composable by agents |
| P2 SOLID Architecture | PASS | SRP per step, OCP via new steps, DIP via port interfaces |
| P3 No Vendor Lock-in | PASS | Uses existing port interfaces, no vendor-specific code |
| P4 Optimised Feedback Loops | PASS | Each step unit-testable with mock ports |
| P5 Best Available Infrastructure | PASS | N/A — no CI/deployment changes |
| P6 Spec-Driven Development | PASS | Full SDD workflow followed |
| P7 No Filling Tests | PASS | Tests guard behavioral contracts per acceptance scenarios |
| P8 ADR | PASS | No port/contract/adapter/deployment changes; internal restructure only |
| Microkernel Architecture | PASS | Pipeline engine is core domain logic in `core/domain/` |
| Hexagonal Boundaries | PASS | Steps receive port interfaces via constructor injection |
| Plugin Contract | PASS | No changes to `PluginContract` protocol |
| Event Schema | PASS | No changes to event schemas |
| Domain Logic Isolation | PASS | Steps accept port interfaces, never import adapters |
| Async-First Design | PASS | All step `execute()` methods are async |
| Simplicity Over Speculation | PASS | Minimal abstraction: 1 protocol + 5 concrete steps |

**Gate result**: PASS — no violations, no justifications needed.

### Post-Design Check

No changes from pre-design check. The design introduces:
- 1 new package (`core/domain/pipeline/`) with 3 files (~370 LOC total)
- 0 new external dependencies
- 0 port/adapter/contract changes
- Constructor injection for all port dependencies

All principles and standards remain satisfied.

## Project Structure

### Documentation (this feature)

```text
specs/004-pipeline-engine-redesign/
├── plan.md              # This file
├── research.md          # Phase 0: design decisions
├── data-model.md        # Phase 1: entity definitions
├── quickstart.md        # Phase 1: development guide
├── contracts/           # Phase 1: pipeline composition API
│   └── pipeline-api.md
└── tasks.md             # Phase 2 (/speckit.tasks — not created by /speckit.plan)
```

### Source Code (repository root)

```text
core/
├── domain/
│   ├── ingest_pipeline.py          # MODIFIED: remove run_ingest_pipeline(), keep data classes
│   ├── summarize_graph.py          # REMOVED: absorbed into pipeline steps
│   └── pipeline/                   # NEW: composable pipeline engine
│       ├── __init__.py             # Public exports
│       ├── engine.py               # IngestEngine, PipelineStep protocol, PipelineContext, StepMetrics
│       ├── steps.py                # ChunkStep, EmbedStep, StoreStep, DocumentSummaryStep, BodyOfKnowledgeSummaryStep
│       └── prompts.py              # Rich summarization prompt templates
├── ports/                          # UNCHANGED
├── adapters/                       # UNCHANGED
└── events/                         # UNCHANGED

plugins/
├── ingest_website/plugin.py        # MODIFIED: compose pipeline using IngestEngine
└── ingest_space/plugin.py          # MODIFIED: compose pipeline using IngestEngine

tests/
├── core/domain/
│   ├── test_ingest_pipeline.py     # MODIFIED: update for data classes only
│   ├── test_summarize_graph.py     # REMOVED: replaced by step tests
│   └── test_pipeline_steps.py      # NEW: unit tests for all pipeline steps
└── plugins/
    ├── test_ingest_website.py      # MODIFIED: update pipeline composition assertions
    └── test_ingest_space.py        # MODIFIED: update pipeline composition assertions
```

**Structure Decision**: Reuses existing `core/domain/` for pipeline engine (domain logic isolation). New `pipeline/` package groups related types without polluting the flat domain namespace. No new top-level directories.

**Actual LOC**: engine.py ~83, steps.py ~346, prompts.py ~44 (total ~473 LOC across 3 files).

## Post-Implementation Corrections

Three correctness bugs were identified during code review and fixed:

1. **`chunks_stored` accuracy** (engine.py, steps.py): `IngestResult.chunks_stored` was using `len(context.chunks)` — total chunks produced, not actually persisted. Fixed by adding `chunks_stored: int` to `PipelineContext`, incremented by StoreStep only on successful batch persistence. See research.md Decision 9.

2. **StoreStep embedding safety** (steps.py): When EmbedStep partially failed, StoreStep sent unembedded chunks to ChromaDB with `embeddings=None`, causing ChromaDB to re-embed them with a different model — creating mixed vector spaces. Fixed by detecting whether EmbedStep ran and skipping unembedded chunks when it did. See research.md Decision 8.

3. **Single-section budget** (steps.py): `_refine_summarize` with 1 section computed `progress=0`, giving only 40% of the budget instead of 100%. Fixed by special-casing `progress=1.0` when `len(chunks)==1`. See research.md Decision 10.

## Complexity Tracking

No violations — table not applicable.
