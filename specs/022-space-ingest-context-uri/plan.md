# Implementation Plan: Space Ingest Context Enrichment & URI Tracking

**Branch**: `022-space-ingest-context-uri` | **Date**: 2026-04-17 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/022-space-ingest-context-uri/spec.md`

## Summary

Enriches the space ingestion pipeline so that each contribution (post, whiteboard, link) is prepended with its parent callout's title and description, preserving hierarchical context that would otherwise be lost during chunking. Simultaneously propagates entity URIs from the Alkemio GraphQL API through the entire pipeline -- from `DocumentMetadata` through `StoreStep` to the vector store -- enabling clickable source links in expert responses.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: Poetry, aio-pika, LangChain, ChromaDB, Pydantic
**Storage**: ChromaDB (vector store)
**Testing**: pytest with asyncio_mode=auto
**Target Platform**: Linux container (K8s)
**Project Type**: Microservice (microkernel + hexagonal architecture)

## Constitution Check

| Principle/Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Changes are fully automatable, no human-in-the-loop required |
| P2 SOLID Architecture | PASS | Changes stay within existing boundaries -- space_reader (plugin), DocumentMetadata (domain), StoreStep (domain) |
| P3 No Vendor Lock-in | N/A | No provider-specific changes |
| P4 Optimised Feedback Loops | PASS | Existing test infrastructure covers these paths |
| P5 Best Available Infrastructure | N/A | No CI changes |
| P6 Spec-Driven Development | PASS | This retrospec documents the feature |
| P7 No Filling Tests | N/A | No test changes in this spec |
| P8 ADR | N/A | No architectural decisions -- extends existing patterns |
| Microkernel Architecture | PASS | Plugin-specific logic stays in plugin; domain model extension is in core/domain |
| Hexagonal Boundaries | PASS | No adapter imports in plugin code |
| Plugin Contract | PASS | No contract changes |
| Event Schema | PASS | No event schema changes |
| Domain Logic Isolation | PASS | DocumentMetadata and StoreStep are internal domain, not ports |
| Async-First | PASS | `read_space_tree` remains async |
| Simplicity Over Speculation | PASS | URI field is optional, context enrichment is minimal logic |

## Project Structure

### Documentation (this feature)

```text
specs/022-space-ingest-context-uri/
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
├── ingest_pipeline.py          # +1 line: uri field on DocumentMetadata
└── pipeline/
    └── steps.py                # ~6 lines: conditional uri in StoreStep metadata

plugins/ingest_space/
└── space_reader.py             # ~60 lines: url in GQL, context enrichment, uri propagation
```

**Structure Decision**: All changes fit within existing module boundaries. No new files or directories needed beyond the spec artifacts.
