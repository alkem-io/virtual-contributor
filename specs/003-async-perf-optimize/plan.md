# Implementation Plan: Async Performance Optimizations

**Branch**: `003-async-perf-optimize` | **Date**: 2026-04-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-async-perf-optimize/spec.md`

## Summary

Optimize the virtual contributor's runtime performance through 7 targeted changes across 5 files: parallelizing independent async operations (document summarization, knowledge store queries), eliminating algorithmic inefficiency (O(n^2) chunk lookup), reducing resource waste (httpx client recreation per retry), removing redundant computation (duplicate batch iteration), and preventing event loop blocking (sync DNS resolution).

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langgraph ^1.0.4, pydantic ^2.11, httpx ^0.27.2, aio-pika 9.5.7, chromadb-client ^1.5.0, beautifulsoup4 ^4.14  
**Storage**: ChromaDB (vector store), RabbitMQ (message transport)  
**Testing**: pytest  
**Target Platform**: Linux server (Docker container)  
**Project Type**: Microkernel service (plugins + core)  
**Performance Goals**: Summarization phase scales ~1/N with document count; guidance queries ~3x faster; connection overhead eliminated during retries  
**Constraints**: Must preserve identical functional output; no interface changes; backward-compatible  
**Scale/Scope**: 5 files modified, 7 optimizations, 0 new interfaces

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle/Standard | Status | Notes |
|--------------------|--------|-------|
| P1 AI-Native Development | PASS | Optimizations are autonomous-friendly, no human workflow changes |
| P2 SOLID Architecture | PASS | No structural changes; plugins still depend on ports, not adapters |
| P3 No Vendor Lock-in | PASS | No vendor-specific changes; httpx client reuse is provider-agnostic |
| P4 Optimised Feedback Loops | PASS | Existing tests remain valid; no new test gaps introduced |
| P5 Best Available Infrastructure | N/A | No CI/CD changes |
| P6 Spec-Driven Development | PASS | This spec retroactively documents the feature |
| P7 No Filling Tests | N/A | No new tests added by this feature; existing tests remain meaningful |
| P8 Architecture Decision Records | N/A | No architectural decisions; these are implementation-level optimizations within existing boundaries |
| Microkernel Architecture | PASS | Core/plugin boundary unchanged |
| Hexagonal Boundaries | PASS | Port/adapter interfaces unchanged |
| Plugin Contract | PASS | Plugin contract unchanged |
| Domain Logic Isolation | PASS | Domain functions still accept port interfaces as parameters |
| Async-First Design | PASS | All changes reinforce async-first: parallel gather, non-blocking DNS, connection reuse |
| Simplicity Over Speculation | PASS | Each optimization addresses a measured bottleneck, no speculative abstractions |

**Gate Result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/003-async-perf-optimize/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
core/
├── adapters/
│   └── openai_compatible_embeddings.py  # Optimization 5: client reuse in retries
├── domain/
│   └── ingest_pipeline.py               # Optimizations 1-3: parallel summarize, O(n) lookup, merged batches
└── ports/                               # (unchanged)

plugins/
├── guidance/
│   └── plugin.py                        # Optimization 4: parallel collection queries
├── ingest_space/
│   └── graphql_client.py                # Optimization 6: client reuse in retries
└── ingest_website/
    └── crawler.py                       # Optimization 7: non-blocking DNS

tests/                                   # (unchanged, existing tests validate behavior)
```

**Structure Decision**: All changes are within existing files in the established core/ and plugins/ layout. No new files, modules, or directories are introduced.

## Complexity Tracking

No violations -- table not applicable.
