# Implementation Plan: Handle Empty Corpus Re-Ingestion

**Branch**: `story/35-handle-empty-corpus-reingestion-cleanup` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/012-empty-corpus-reingestion/spec.md`

## Summary

Fix the empty-corpus re-ingestion gap in both `IngestSpacePlugin` and `IngestWebsitePlugin`. When a fetch/crawl succeeds but returns zero documents, run a minimal cleanup pipeline (`ChangeDetectionStep` + `OrphanCleanupStep`) to delete all previously stored chunks from the collection. Previously, both plugins returned early with no side effects, leaving stale data in the knowledge store. The fix reuses the existing `IngestEngine` and pipeline steps with no new abstractions.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: langchain ^1.1.0, pydantic-settings ^2.11.0, aio-pika (unchanged)
**Storage**: ChromaDB (unchanged, existing pipeline steps reused)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: N/A (bug fix, no performance-sensitive path)
**Constraints**: No new dependencies; no changes to pipeline step implementations; reuse existing `IngestEngine`
**Scale/Scope**: 2 plugin files modified (~15 lines each), 2 test files modified (~85 lines each)

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Bug fix with zero human interaction required in delivery |
| P2 | SOLID Architecture | PASS | No new interfaces. Reuses existing `IngestEngine` + steps. Open/Closed satisfied -- plugins gain behavior without modifying core |
| P3 | No Vendor Lock-in | N/A | No provider changes |
| P4 | Optimised Feedback Loops | PASS | New unit tests cover empty-successful and failure scenarios for both plugins |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts in specs/012-empty-corpus-reingestion/ |
| P7 | No Filling Tests | PASS | All new tests guard meaningful behavioral contracts: cleanup runs on empty corpus, failure preserved on exception |
| P8 | ADR | N/A | No port/contract changes, no new dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Changes confined to plugin code. No core modifications |
| AS:Hexagonal | Hexagonal Boundaries | PASS | Plugins interact with knowledge store via `KnowledgeStorePort`. No adapter imports |
| AS:Plugin | Plugin Contract | PASS | `PluginContract` unchanged. `handle()` signature and return types identical |
| AS:Domain | Domain Logic Isolation | PASS | Reuses `IngestEngine` and pipeline steps as-is. No domain changes |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal fix: 2 files, ~15 lines each. No new abstractions or config |
| AS:Async | Async-First Design | PASS | All code paths remain async. `IngestEngine.run()` is async |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/012-empty-corpus-reingestion/
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
plugins/
├── ingest_space/
│   └── plugin.py          # Replace early return on empty documents with cleanup pipeline
└── ingest_website/
    └── plugin.py          # Replace early return on empty documents with cleanup pipeline

tests/
└── plugins/
    ├── test_ingest_space.py   # Add empty-cleanup and failure-no-cleanup tests
    └── test_ingest_website.py # Add empty-cleanup, empty-extract, and failure-no-cleanup tests
```

## Complexity Tracking

No constitution violations to justify.
