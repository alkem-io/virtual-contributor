# Implementation Plan: Retry Error Reporting

**Branch**: `024-retry-error-reporting` | **Date**: 2026-04-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/024-retry-error-reporting/spec.md`

## Summary

Refactors the engine query error handling to centralize error response publishing in `_retry_or_reject`. Intermediate retries are silent — only the final exhausted attempt publishes an error response to the user. This eliminates the previous pattern of publishing an error message on every failure, which spammed the chat room.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: Poetry, aio-pika, asyncio
**Storage**: N/A (message handling logic)
**Testing**: pytest with asyncio_mode=auto
**Target Platform**: Linux container (K8s)
**Project Type**: Microservice (microkernel + hexagonal architecture)

## Constitution Check

| Principle/Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Simple refactor, fully automatable |
| P2 SOLID Architecture | PASS | Single responsibility — `_retry_or_reject` owns retry+error logic |
| P3 No Vendor Lock-in | N/A | No provider changes |
| P4 Optimised Feedback Loops | PASS | Testable in isolation |
| P6 Spec-Driven Development | PASS | This retrospec documents the change |
| P7 No Filling Tests | N/A | No test changes |
| P8 ADR | N/A | No architectural decision — behavioral refinement |
| Microkernel Architecture | PASS | Changes in main.py (application startup/wiring layer) |
| Plugin Contract | PASS | No contract changes |
| Event Schema | PASS | Uses existing Response event |
| Async-First | PASS | All functions remain async |
| Simplicity Over Speculation | PASS | Removes duplication, adds no abstractions |

## Project Structure

### Documentation (this feature)

```text
specs/024-retry-error-reporting/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code

```text
main.py                         # ~50 lines changed: retry/error consolidation
```

**Structure Decision**: Single file change — all modifications in the `_run` function's inner closures.
