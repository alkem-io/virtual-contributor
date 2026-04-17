# Implementation Plan: PromptGraph Robustness & Expert Plugin Integration

**Branch**: `023-promptgraph-robustness` | **Date**: 2026-04-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/023-promptgraph-robustness/spec.md`

## Summary

Makes the PromptGraph engine production-ready for Alkemio's real-world prompt graph definitions by adding schema normalization (list->dict properties), nullable field handling, structured output recovery from malformed LLM responses, and Pydantic model state compatibility. Simultaneously fixes the expert plugin's graph integration to use correct state keys and populate conversation history.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: Poetry, LangChain, LangGraph, Pydantic, json_schema_to_pydantic
**Storage**: N/A (PromptGraph is in-memory execution)
**Testing**: pytest with asyncio_mode=auto
**Target Platform**: Linux container (K8s)
**Project Type**: Microservice (microkernel + hexagonal architecture)

## Constitution Check

| Principle/Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Changes are fully automatable |
| P2 SOLID Architecture | PASS | PromptGraph is in core/domain (domain logic isolation). Expert plugin changes stay in plugin. |
| P3 No Vendor Lock-in | PASS | `runnable_llm` unwrapping makes PromptGraph work with any LLMPort adapter, not just raw LangChain models |
| P4 Optimised Feedback Loops | PASS | All new methods are pure/testable |
| P6 Spec-Driven Development | PASS | This retrospec documents the feature |
| P7 No Filling Tests | N/A | No test changes |
| P8 ADR | N/A | No new architectural decisions — enhances existing PromptGraph design |
| Microkernel Architecture | PASS | Domain logic in core/domain, plugin logic in plugin |
| Hexagonal Boundaries | PASS | Expert plugin accesses PromptGraph via import (domain logic, not adapter). No adapter imports in plugin. |
| Plugin Contract | PASS | No contract changes |
| Domain Logic Isolation | PASS | PromptGraph accepts LLM as parameter (DI), doesn't import adapters |
| Simplicity Over Speculation | PASS | Each addition solves a concrete production failure mode |

## Project Structure

### Documentation (this feature)

```text
specs/023-promptgraph-robustness/
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
core/domain/
└── prompt_graph.py             # +200 lines: schema normalization, recovery, state handling

plugins/expert/
└── plugin.py                   # ~30 lines: retrieve return key, conversation history, query selection
```

**Structure Decision**: All changes fit within existing module boundaries.
