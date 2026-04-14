# Implementation Plan: Skip Upsert for Unchanged Chunks in StoreStep

**Branch**: `story/1825-skip-upsert-unchanged-chunks` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/016-skip-unchanged-upsert/spec.md`

## Summary

Add an unchanged-chunk filter to `StoreStep.execute()` that skips chunks whose `content_hash` appears in `PipelineContext.unchanged_chunk_hashes`, eliminating redundant ChromaDB upserts on incremental ingests. The filter leverages existing data structures populated by ChangeDetectionStep; no new models, ports, or configuration fields are introduced.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: No new dependencies. Uses existing `PipelineContext`, `Chunk`, `KnowledgeStorePort`.
**Storage**: ChromaDB (unchanged, fewer writes on incremental ingest)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: Eliminate up to 98% of redundant upsert calls on incremental ingest
**Constraints**: Full backward compatibility; no port interface changes; no Chunk dataclass changes
**Scale/Scope**: 2 files modified, ~30 lines added

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Pure code change, no interactive steps |
| P2 | SOLID Architecture | PASS | No new interfaces. StoreStep internal logic change only (Open/Closed satisfied since no core changes) |
| P3 | No Vendor Lock-in | N/A | No provider-specific changes |
| P4 | Optimised Feedback Loops | PASS | 4 new unit tests with deterministic assertions |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts produced |
| P7 | No Filling Tests | PASS | Each test guards a distinct behavioral contract (skip unchanged, store changed, pass summary, backward compat) |
| P8 | ADR | N/A | No port/contract changes, no new dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Change is within domain logic in `core/domain/pipeline/steps.py` |
| AS:Hexagonal | Hexagonal Boundaries | PASS | StoreStep calls `KnowledgeStorePort.ingest()` through existing port interface |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged |
| AS:Domain | Domain Logic Isolation | PASS | StoreStep is internal domain logic, tested with mock ports |
| AS:Simplicity | Simplicity Over Speculation | PASS | Reuses existing `unchanged_chunk_hashes` set. No new abstractions |
| AS:Async | Async-First Design | PASS | No new sync calls |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/016-skip-unchanged-upsert/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
core/
└── domain/
    └── pipeline/
        └── steps.py           # Filter unchanged chunks in StoreStep.execute()

tests/
└── core/
    └── domain/
        └── test_pipeline_steps.py  # 4 new tests for skip-unchanged behavior
```

## Complexity Tracking

No constitution violations to justify.
