# Implementation Plan: Configurable Vector DB Distance Function

**Branch**: `develop` | **Date**: 2026-04-08 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/009-vector-db-distance-fn/spec.md`

## Summary

Add a configurable distance function (`cosine`, `l2`, `ip`) for ChromaDB vector similarity search, exposed via the `VECTOR_DB_DISTANCE_FN` environment variable. The value is validated at config load time and passed through to all ChromaDB collection operations as HNSW space metadata. Default is `cosine` for full backward compatibility.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: chromadb-client ^1.5.0, pydantic-settings ^2.11.0
**Storage**: ChromaDB (vector store via HTTP client)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: N/A (configuration change)
**Constraints**: Full backward compatibility when env var is unset
**Scale/Scope**: 3 files modified, ~25 lines added

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Config-only change, no interactive steps |
| P2 | SOLID Architecture | PASS | No new interfaces. ChromaDBAdapter gains one constructor param — Open/Closed satisfied |
| P3 | No Vendor Lock-in | PASS | Distance function is a ChromaDB-specific concept but exposed generically via config |
| P4 | Optimised Feedback Loops | PASS | Validation at startup provides immediate feedback on misconfiguration |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Retrospec in progress |
| P7 | No Filling Tests | N/A | No tests added in this changeset |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Config stays in core, adapter change is internal |
| AS:Hexagonal | Hexagonal Boundaries | PASS | KnowledgeStorePort unchanged. Adapter-internal change only |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged |
| AS:Domain | Domain Logic Isolation | PASS | No domain logic changes |
| AS:Simplicity | Simplicity Over Speculation | PASS | Single field, single validation, direct passthrough |
| AS:Async | Async-First Design | PASS | No new sync calls |

**Gate result**: PASS — no violations.

## Project Structure

### Documentation (this feature)

```text
specs/009-vector-db-distance-fn/
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
├── config.py              # Add vector_db_distance_fn field + validation
└── adapters/
    └── chromadb.py         # Accept distance_fn param, pass to collection metadata

main.py                    # Pass distance_fn from config to ChromaDBAdapter

.env.example               # Document VECTOR_DB_DISTANCE_FN
```

## Complexity Tracking

No constitution violations to justify.
