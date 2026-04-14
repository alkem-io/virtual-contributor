# Implementation Plan: Pipeline Engine Safety -- Formalize Destructive Step Handling

**Branch**: `story/37-pipeline-engine-safety-destructive-step-handling` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/011-pipeline-destructive-step-safety/spec.md`

## Summary

Add engine-level `destructive` flag support to pipeline steps. `IngestEngine.run()` skips destructive steps when prior errors exist, replacing the fragile string-matching guard in `OrphanCleanupStep`. The `PipelineStep` protocol remains unchanged -- the flag is opt-in via duck typing (`getattr` with default). `OrphanCleanupStep` declares itself destructive and its manual guard is removed.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: No new dependencies. Existing: pydantic-settings ^2.11.0
**Storage**: ChromaDB (unchanged)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: N/A (safety mechanism, no performance impact)
**Constraints**: Full backward compatibility; PipelineStep protocol unchanged; sequential execution model preserved (ADR-0004)
**Scale/Scope**: 3 files modified, ~50 lines added, ~10 lines removed

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Pure code change, no interactive steps |
| P2 | SOLID Architecture | PASS | Open/Closed: new behavior via opt-in property, no protocol modification. Single Responsibility: engine handles gating, steps declare intent |
| P3 | No Vendor Lock-in | N/A | No provider changes |
| P4 | Optimised Feedback Loops | PASS | 7 new meaningful tests covering gating behavior, metrics, and message format |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts produced |
| P7 | No Filling Tests | PASS | Every test guards a specific behavioral contract or boundary condition |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Change localized to core domain logic. No cross-plugin coupling |
| AS:Hexagonal | Hexagonal Boundaries | PASS | No port or adapter changes |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged. Ingest plugins unaffected |
| AS:Domain | Domain Logic Isolation | PASS | Engine and step changes are internal to core/domain/pipeline/ |
| AS:Simplicity | Simplicity Over Speculation | PASS | Single boolean flag + getattr. No phase model, no new protocols, no abstractions |
| AS:Async | Async-First Design | PASS | No new sync calls |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/011-pipeline-destructive-step-safety/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── clarifications.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
core/
└── domain/
    └── pipeline/
        ├── engine.py      # Add destructive-step gating logic in IngestEngine.run()
        └── steps.py       # Add destructive property to OrphanCleanupStep; remove string guard

tests/
└── core/
    └── domain/
        └── test_pipeline_steps.py  # 7 new tests + 2 updated tests
```

## Complexity Tracking

No constitution violations to justify.
