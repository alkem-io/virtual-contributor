# Implementation Plan: Ingest Space Knowledge-Base Routing

**Branch**: `033-ingest-space-kb-routing` | **Date**: 2026-05-11 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/033-ingest-space-kb-routing/spec.md`

## Summary

Branch the ingest-space plugin on the inbound event's `type` field so that
`alkemio-knowledge-base` bodies of knowledge are fetched via
`lookup.knowledgeBase(ID:)` instead of `lookup.space(ID:)`. The fix is entirely
client-side. A new `read_knowledge_base_tree` reader normalises the
knowledge-base GraphQL response into the dict shape the existing
`_process_space` traversal already understands (synthetic
`collaboration.calloutsSet`, empty `subspaces`), so all callout / post /
whiteboard / link handling is reused unchanged. A thin `read_body_of_knowledge`
dispatcher selects the reader from `event.type`, with unknown types falling back
to the space reader to preserve today's behaviour for the dominant case. The
plugin logs the resolved type for operator visibility.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: httpx (GraphQL transport), Pydantic v2 (event models), aio-pika (RabbitMQ)
**Storage**: ChromaDB via `KnowledgeStorePort` (unchanged by this feature)
**Testing**: pytest with `asyncio_mode = "auto"`; in-memory mocks in `tests/conftest.py` (`MockEmbeddingsPort`, `MockKnowledgeStorePort`, `MockLLMPort`) and the test factory `make_ingest_body_of_knowledge`
**Target Platform**: Linux container (single image, `PLUGIN_TYPE=ingest_space`)
**Project Type**: Microkernel + Hexagonal Python service
**Performance Goals**: No measurable change — the knowledge-base query is structurally simpler than the space tree query (no subspaces). Round-trip cost is dominated by network and server work, not the query string.
**Constraints**: Wire contract (`IngestBodyOfKnowledge` / `IngestBodyOfKnowledgeResult`) MUST NOT change. Public function `read_space_tree` MUST keep its signature for backward compatibility.
**Scale/Scope**: One plugin (`ingest_space`), one module (`space_reader.py`), three return sites in `plugin.handle`. ~80 lines added in `space_reader.py`, ~10 lines in `plugin.py`, ~170 lines of tests.

## Constitution Check

| Principle / Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Change is small, deterministic, fully covered by automated tests. Routing decision is gated by tests so no human verification is needed beyond CI. |
| P2 SOLID Architecture | PASS | Single Responsibility preserved — `read_space_tree` keeps its existing behaviour; the new reader has the single job of walking a knowledge base; the dispatcher has the single job of picking between them. Open/Closed: adding the new path required zero changes to `_process_space` semantics (only an additive optional parameter). |
| P3 No Vendor Lock-in | N/A | No LLM/embedding/provider code touched. |
| P4 Optimised Feedback Loops | PASS | Twelve new tests added alongside the implementation. All run locally under `poetry run pytest tests/plugins/test_ingest_space.py` in under a second. CI runs the same suite. |
| P5 Best Available Infrastructure | N/A | No CI/CD change. |
| P6 Spec-Driven Development | PASS | This retrospec records the spec for an urgent bug fix shipped on a `fix/…` branch. The fix was small enough to qualify for P6's bug-fix exception clause but is promoted to a full SDD artifact set for traceability and to gate any future routing changes against the test suite. |
| P7 No Filling Tests | PASS | Each new test guards a real behavioural contract — the dispatcher's branching, the KB reader's GraphQL choice, the root-document type tag, and end-to-end plugin propagation. No trivial getters, no framework re-assertions. |
| P8 Architecture Decision Records | N/A | No port interface, plugin contract, or wire-format change. The new GraphQL query is an internal client choice — `lookup.knowledgeBase` is a pre-existing server endpoint. |
| Microkernel Architecture | PASS | Change confined to `plugins/ingest_space/`. Core untouched. No cross-plugin coupling. |
| Plugin Contract | PASS | `PluginContract` protocol unchanged; the plugin still handles `IngestBodyOfKnowledge` and returns `IngestBodyOfKnowledgeResult`. |
| Event Schema as Wire Contract | PASS | No field added, renamed, retyped, or removed on either event. The existing `type` field is now read (it was previously ignored); semantics of `type` are clarified by use, not by schema change. |
| Domain Logic Isolation | PASS | The ingest pipeline (`core/domain/pipeline`) is unchanged. The plugin still composes `ChunkStep`, `ContentHashStep`, `ChangeDetectionStep`, `EmbedStep`, `StoreStep`, and the summarisation steps exactly as before. |
| Async-First Design | PASS | All new functions are `async def`. GraphQL calls go through the existing async client. |
| Simplicity Over Speculation | PASS | The KB reader reuses `_process_space` via a synthetic-shape adapter rather than duplicating callout traversal code. The dispatcher is a six-line `if/else`. The new `top_doc_type` parameter is the minimal hook required to differentiate root tagging — no broader refactor of `_process_space`. |

## Project Structure

### Documentation (this feature)

```text
specs/033-ingest-space-kb-routing/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── contracts/
│   └── ingest-graphql-lookup.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
plugins/
└── ingest_space/
    ├── space_reader.py         # Modified: KB query, KB reader, dispatcher, top_doc_type kwarg
    └── plugin.py               # Modified: dispatch on event.type; log resolved type

tests/
└── plugins/
    └── test_ingest_space.py    # Modified: KB reader, dispatcher, plugin dispatch tests
```

**Structure Decision**: Standard microkernel layout. Every change lives inside the `ingest_space` plugin module and its dedicated test file. Nothing in `core/` is touched. No new files are introduced.

## Complexity Tracking

No constitution violations — this section is not applicable.
