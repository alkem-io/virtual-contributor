# Implementation Plan: Summary Lifecycle Management

**Branch**: `story/36-summary-lifecycle-cleanup` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/013-summary-lifecycle-management/spec.md`

## Summary

Fix two edge cases where stale summaries persist in the knowledge store after re-ingestion: (1) per-document summaries remain when a changed document drops below the summary threshold, and (2) the BoK summary persists when all documents are removed from the corpus. Both fixes add orphan IDs to `context.orphan_ids` so the existing `OrphanCleanupStep` handles deletion. No architectural changes; localized additions to two existing pipeline steps.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: langchain ^1.1.0, pydantic-settings ^2.11.0
**Storage**: ChromaDB (unchanged)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: N/A (edge-case bug fix, no hot path change)
**Constraints**: Changes limited to `core/domain/pipeline/steps.py` and corresponding tests
**Scale/Scope**: 1 source file modified (~24 lines added), 1 test file modified (~162 lines added)

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Bug fix, no interactive steps |
| P2 | SOLID Architecture | PASS | No new interfaces. Existing `PipelineStep` protocol unchanged. Steps gain internal logic only |
| P3 | No Vendor Lock-in | N/A | No provider-specific changes |
| P4 | Optimised Feedback Loops | PASS | 7 new unit tests with meaningful assertions covering all edge cases |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts produced |
| P7 | No Filling Tests | PASS | Each test validates a distinct behavioral edge case; no filler |
| P8 | ADR | N/A | No port/contract changes, no new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Changes are in core domain logic, not plugin-specific |
| AS:Hexagonal | Hexagonal Boundaries | PASS | No adapter or port changes |
| AS:Plugin | Plugin Contract | PASS | `PluginContract` unchanged |
| AS:Domain | Domain Logic Isolation | PASS | Steps accept port interfaces as parameters; testable with mock ports |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal additions using existing `orphan_ids` mechanism |
| AS:Async | Async-First Design | PASS | No new sync calls |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/013-summary-lifecycle-management/
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
        └── steps.py          # Add stale-summary detection + empty-corpus BoK cleanup

tests/
└── core/
    └── domain/
        └── test_pipeline_steps.py  # Add 7 test cases in 3 new test classes
```

## Complexity Tracking

No constitution violations to justify.
