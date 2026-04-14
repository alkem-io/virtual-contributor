# Implementation Plan: Incremental Embedding

**Branch**: `story/1826-incremental-embedding` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/017-incremental-embedding/spec.md`

## Summary

Reduce ingest pipeline wall-clock time by embedding each document's chunks inline immediately after its summary is produced, overlapping LLM-bound summarization I/O with GPU-bound embedding I/O. `DocumentSummaryStep` gains an optional `embeddings_port` parameter; when provided, it embeds content chunks and the summary chunk per-document. `EmbedStep` remains as a safety net for un-embedded chunks (BoK summary, below-threshold documents, failed inline embeddings). Both ingest plugins pass their embeddings port to the updated step.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: langchain ^1.1.0, pydantic-settings ^2.11.0
**Storage**: ChromaDB (unchanged)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: Reduce ingest pipeline wall-clock time by overlapping summarization and embedding I/O
**Constraints**: Full backward compatibility; no pipeline engine, context, or domain model changes
**Scale/Scope**: 3 files modified (~60 lines added), 1 test file extended (~180 lines)

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Pure code change, no interactive steps |
| P2 | SOLID Architecture | PASS | Open/Closed: `DocumentSummaryStep` extended with optional param, no interface changes. Single Responsibility: embedding logic is a private helper within the step |
| P3 | No Vendor Lock-in | PASS | Uses existing `EmbeddingsPort` protocol, no provider-specific code |
| P4 | Optimised Feedback Loops | PASS | 6 new unit tests covering all paths |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts in specs/017-incremental-embedding/ |
| P7 | No Filling Tests | PASS | Each test guards a specific behavioral contract: inline embedding, safety-net skip, error handling, backward compat, threshold, full pipeline |
| P8 | ADR | PASS | No port/contract changes, no new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Change is in domain logic (`core/domain/pipeline/steps.py`) and plugin wiring. No cross-plugin coupling |
| AS:Hexagonal | Hexagonal Boundaries | PASS | Uses existing `EmbeddingsPort` — same port, same adapter, additional injection point |
| AS:Plugin | Plugin Contract | PASS | `PluginContract` unchanged. Plugins pass existing embeddings port to step constructor |
| AS:Domain | Domain Logic Isolation | PASS | `DocumentSummaryStep` accepts `EmbeddingsPort` via constructor injection, does not import adapters |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal change: one optional param, one private helper. No new abstractions, no config changes |
| AS:Async | Async-First Design | PASS | Inline embedding uses `await self._embeddings.embed()` |

**Gate result**: PASS — no violations.

## Project Structure

### Documentation (this feature)

```text
specs/017-incremental-embedding/
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
        └── steps.py           # DocumentSummaryStep: +embeddings_port, +_embed_document_chunks()

plugins/
├── ingest_space/
│   └── plugin.py              # Pass self._embeddings to DocumentSummaryStep
└── ingest_website/
    └── plugin.py              # Pass self._embeddings to DocumentSummaryStep

tests/
└── core/
    └── domain/
        └── test_pipeline_steps.py  # 6 new tests for incremental embedding
```

## Complexity Tracking

No constitution violations to justify.
