# Implementation Plan: Concurrent Document Summarization in DocumentSummaryStep

**Branch**: `story/1823-implement-actual-concurrency-in-document-summary-step` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/014-concurrent-document-summary/spec.md`

## Summary

Replace the sequential `for` loop in `DocumentSummaryStep.execute()` with concurrent execution using `asyncio.Semaphore` + `asyncio.gather`. Introduce a `_SummaryResult` dataclass to collect results from concurrent tasks, then apply them to `PipelineContext` in deterministic order after all tasks complete (collect-and-apply pattern). This avoids race conditions on shared mutable state while delivering 5-10x speedup for multi-document ingest workloads.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: asyncio (stdlib), dataclasses (stdlib)
**Storage**: N/A (no storage changes)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: 5-10x speedup for multi-document summarization; wall-clock time proportional to `ceil(N / concurrency)` rather than `N`
**Constraints**: No port interface changes; backward compatible; deterministic output ordering
**Scale/Scope**: 2 files modified, ~297 net lines added (mostly tests)

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Pure code change, no interactive steps |
| P2 | SOLID Architecture | PASS | Single Responsibility: only DocumentSummaryStep modified. Open/Closed: no interface changes |
| P3 | No Vendor Lock-in | N/A | No provider-specific changes |
| P4 | Optimised Feedback Loops | PASS | 6 new tests covering concurrency, ordering, partial failure, and context integrity |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Retrospec in progress |
| P7 | No Filling Tests | PASS | All 6 tests verify meaningful behavioral contracts: timing, ordering, failure isolation, state integrity |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Change is in core/domain (shared domain logic), not in plugins |
| AS:Hexagonal | Hexagonal Boundaries | PASS | No adapter or port changes. LLMPort interface unchanged |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged. Plugins unaware of internal concurrency |
| AS:Domain | Domain Logic Isolation | PASS | DocumentSummaryStep is domain logic in core/domain/pipeline/steps.py, accepts LLMPort via DI |
| AS:Simplicity | Simplicity Over Speculation | PASS | Uses stdlib asyncio primitives (Semaphore + gather). No new abstractions or frameworks |
| AS:Async | Async-First Design | PASS | Replaces sequential loop with proper async concurrency using asyncio.gather |

**Gate result**: PASS --- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/014-concurrent-document-summary/
    spec.md
    plan.md
    research.md
    data-model.md
    quickstart.md
    tasks.md
    checklists/
        requirements.md
```

### Source Code (repository root)

```text
core/
    domain/
        pipeline/
            steps.py           # Refactor DocumentSummaryStep.execute() for concurrency;
                               # add _SummaryResult dataclass

tests/
    core/
        domain/
            test_pipeline_steps.py  # Add TestDocumentSummaryStepConcurrency (6 tests),
                                    # _DelayedLLMPort, _SelectiveFailLLMPort helpers
```

## Complexity Tracking

No constitution violations to justify.
