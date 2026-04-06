# Implementation Plan: Content-Hash Deduplication and Orphan Cleanup

**Branch**: `006-content-hash-dedup` | **Date**: 2026-04-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-content-hash-dedup/spec.md`

## Summary

SHA-256 content fingerprints become the chunk ID in the knowledge store (content-addressable storage), enabling three capabilities: (1) skip re-embedding of unchanged chunks during re-ingestion, (2) automatic orphan cleanup when chunking parameters change, and (3) reliable change detection between ingestion cycles. This requires extending `KnowledgeStorePort` with `get()` and `delete()` methods, adding three new pipeline steps (`ContentHashStep`, `ChangeDetectionStep`, `OrphanCleanupStep`), modifying `EmbedStep` and `StoreStep` to respect dedup flags, and removing the destructive `delete_collection()` calls from both ingestion plugins.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: langchain ^1.1.0, langchain-text-splitters ^0.3.8, chromadb-client ^1.5.0, pydantic ^2.11, aio-pika 9.5.7, hashlib (stdlib)
**Storage**: ChromaDB (vector store via HTTP client)
**Testing**: pytest (`poetry run pytest`)
**Target Platform**: Linux server (Docker container)
**Project Type**: Service (message-driven microservice with plugin architecture)
**Performance Goals**: >80% embedding skip rate on unchanged re-ingestion (SC-001); measurably faster re-ingestion (SC-002)
**Constraints**: SHA-256 hashing overhead negligible vs embedding costs (~µs vs ~ms per chunk)
**Scale/Scope**: Per-document chunking; typical corpus sizes in the hundreds of documents

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Phase 0 Evaluation

| Principle / Standard | Verdict | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Feature is pipeline automation — zero human interaction in the delivery path |
| P2 SOLID Architecture | PASS | **S**: Each new step has a single responsibility (hash, detect, cleanup). **O**: New steps added without modifying existing step logic. **L**: ChromaDB adapter changes are internal — no plugin behavior changes. **I**: `get()` and `delete()` are fundamental CRUD operations the port was missing, not feature-specific bloat. **D**: All new steps depend on port interfaces, never on adapters. |
| P3 No Vendor Lock-in | PASS | All ChromaDB-specific code stays in `core/adapters/chromadb.py`. New `get()` and `delete()` are technology-agnostic port methods. |
| P4 Optimised Feedback Loops | PASS | New tests cover skip-unchanged, detect-changed, orphan-cleanup per SC-005. |
| P5 Best Available Infrastructure | N/A | No CI/CD changes required. |
| P6 Spec-Driven Development | PASS | Following full SDD workflow. |
| P7 No Filling Tests | PASS | Each new test validates a specific behavioral contract. |
| P8 ADR Required | **ACTION** | Port interface extension (`get()`, `delete()`) + content-addressable storage scheme qualifies as a major architectural decision. ADR to be created during implementation. |
| Microkernel Architecture | PASS | All changes in `core/` domain logic. Plugins only change pipeline step composition. |
| Hexagonal Boundaries | PASS | New methods added to port protocol and implemented in adapter. Pipeline steps receive ports via constructor DI. |
| Domain Logic Isolation | PASS | New steps in `core/domain/pipeline/steps.py` accept port interfaces as parameters. |
| Async-First Design | PASS | All new port methods and pipeline steps are `async`. |
| Simplicity Over Speculation | PASS | Three new steps are the minimum needed. No speculative abstractions. |

**Gate result**: PASS — no violations. One action item: create ADR during implementation.

### Post-Phase 1 Re-evaluation

Design artifacts reviewed against constitution. No new violations introduced:

| Concern | Assessment |
|---|---|
| Port extension scope | `get()` and `delete()` are minimal CRUD completions, not feature-specific bloat. `GetResult` mirrors `QueryResult` shape. **P2-I**: PASS. |
| Hybrid ID scheme (content-hash + deterministic) | Content-hash for content chunks, deterministic for summaries. No speculative abstraction — each scheme serves a specific, necessary purpose. **Simplicity**: PASS. |
| `PipelineContext` field additions | Six new fields track dedup state. All are consumed by specific steps. No god-object concern — context is a pipeline-scoped data bag by design. **P2-S**: PASS. |
| `DocumentSummaryStep` behavior change | Skip logic is additive — checks `change_detection_ran` flag and `changed_document_ids` to disambiguate "no changes" from "no change detection step". Unchanged documents produce identical results to before. **Backward compat**: PASS. |
| `BodyOfKnowledgeSummaryStep` behavior change | Skips regeneration when `change_detection_ran` is True and `changed_document_ids` is empty (no content changed). Regenerates if any document changed, or if change detection didn't run (backward compat). **Backward compat**: PASS. |
| `delete_collection()` removal from plugins | Moves from destructive wipe to incremental update. Strictly safer. `delete_collection()` retained on port for admin use. **No regression**: PASS. |
| ADR requirement | Port interface change confirmed → ADR `docs/adr/000X-content-hash-dedup.md` required at implementation time. **P8**: ACTION remains. |

**Post-design gate result**: PASS.

## Project Structure

### Documentation (this feature)

```text
specs/006-content-hash-dedup/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── knowledge-store-port.md
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
core/
├── ports/
│   └── knowledge_store.py          # Extended: add get(), delete(), GetResult
├── adapters/
│   └── chromadb.py                 # Extended: implement get(), delete()
├── domain/
│   ├── ingest_pipeline.py          # Extended: content_hash field on Chunk
│   └── pipeline/
│       ├── engine.py               # Extended: dedup tracking fields + change_detection_ran flag on PipelineContext
│       └── steps.py                # New: ContentHashStep, ChangeDetectionStep, OrphanCleanupStep
│                                   # Modified: StoreStep (content-hash IDs), DocumentSummaryStep & BoKSummaryStep (skip unchanged via flag)

plugins/
├── ingest_space/plugin.py          # Modified: remove delete_collection(), wire new steps
└── ingest_website/plugin.py        # Modified: remove delete_collection(), wire new steps

tests/
└── core/domain/
    ├── test_pipeline_steps.py      # Extended: tests for new steps + modified steps
    └── test_content_hash.py        # New: content hash unit tests (determinism, sensitivity)

docs/
└── adr/
    └── 000X-content-hash-dedup.md  # New: ADR for port extension + content-addressable storage
```

**Structure Decision**: All changes fit within the existing `core/` + `plugins/` + `tests/` layout. No new top-level directories needed.

## Complexity Tracking

No constitution violations to justify — all gates pass.
