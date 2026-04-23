# Implementation Plan: PromptGraph Field Recovery

**Branch**: `029-promptgraph-field-recovery` | **Date**: 2026-04-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/029-promptgraph-field-recovery/spec.md`

## Summary

Adds type-aware default filling to `PromptGraph._recover_fields` so that missing required fields from small/terse LLMs are filled with sensible defaults (`""`, `0`, `False`, `[]`, `{}`) instead of aborting the entire recovery. A new static method `_default_for_annotation` maps Python type annotations to safe defaults, with `Optional[X]` unwrapping. Warning logs identify filled fields for observability.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: Pydantic v2, LangGraph, LangChain
**Storage**: N/A (in-memory recovery logic)
**Testing**: pytest with asyncio_mode=auto
**Target Platform**: Linux container (K8s)
**Project Type**: Microservice (microkernel + hexagonal architecture)

## Constitution Check

| Principle/Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Single-concern fix, fully automatable |
| P2 SOLID Architecture | PASS | Single Responsibility -- `_default_for_annotation` has one job; `_recover_fields` has one job. No new classes or interfaces needed |
| P3 No Vendor Lock-in | N/A | No provider-specific changes; fix benefits all LLM providers |
| P4 Optimised Feedback Loops | PASS | 7 new targeted tests; all deterministic; local pytest execution |
| P5 Best Available Infrastructure | N/A | No CI/CD changes |
| P6 Spec-Driven Development | PASS | This retrospec documents the change |
| P7 No Filling Tests | PASS | Each test guards a specific behavioral contract (type default, regression case) |
| P8 ADR | N/A | No architectural decision -- behavioral enhancement within existing recovery mechanism |
| Microkernel Architecture | PASS | Changes in `core/domain/` -- shared internal logic, not a plugin |
| Hexagonal Boundaries | PASS | No port or adapter changes |
| Plugin Contract | PASS | No contract changes |
| Event Schema | PASS | No event model changes |
| Domain Logic Isolation | PASS | `_recover_fields` and `_default_for_annotation` are domain logic in `core/domain/prompt_graph.py` |
| Async-First | PASS | Recovery is synchronous by design (pure data transformation inside an async node) |
| Simplicity Over Speculation | PASS | Handles exactly the types Pydantic models use; no speculative extensions |

## Project Structure

### Documentation (this feature)

```text
specs/029-promptgraph-field-recovery/
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
core/domain/prompt_graph.py                    # ~40 lines added: _default_for_annotation + _recover_fields fill logic
tests/core/domain/test_prompt_graph.py         # ~80 lines added: 7 new tests in TestRecoverFields
```

**Structure Decision**: Two-file change -- the recovery logic and its tests. Both are in `core/domain/`, consistent with the Domain Logic Isolation standard.
