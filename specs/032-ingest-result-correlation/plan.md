# Implementation Plan: Ingest Website Result Correlation Fields

**Branch**: `032-ingest-result-correlation` | **Date**: 2026-04-30 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/032-ingest-result-correlation/spec.md`

## Summary

Add four identification fields (`bodyOfKnowledgeId`, `type`, `purpose`, `personaId`) to the `IngestWebsiteResult` event envelope and have `IngestWebsitePlugin.handle` copy them through from the inbound `IngestWebsite` request on every return path (cleanup-only, success, failure, exception). The change is additive on the wire — all four fields default to empty strings so any caller that does not yet populate them continues to work, and any consumer that does not yet read them is unaffected. The motivation is that the alkemio-server result handler must correlate the result back to the persona that owns the body of knowledge, and prior to this change the envelope carried only `result`, `error`, and `timestamp` — not enough to identify the originating request.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: Pydantic v2 (event models), aio-pika (RabbitMQ transport)
**Storage**: N/A — pure event schema and plugin handler change
**Testing**: pytest with `asyncio_mode = "auto"`; existing mock ports in `tests/conftest.py`
**Target Platform**: Linux container (single image, `PLUGIN_TYPE=ingest_website`)
**Project Type**: Microkernel + Hexagonal Python service
**Performance Goals**: No measurable performance impact — four extra string fields on a low-frequency result envelope
**Constraints**: Wire format MUST remain backward-compatible with existing alkemio-server deployments; no coordinated release required
**Scale/Scope**: Single plugin (`ingest_website`), single event model (`IngestWebsiteResult`), three return sites in `plugin.handle`

## Constitution Check

| Principle / Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Change is small, deterministic, fully covered by automated tests; no human verification needed beyond CI. |
| P2 SOLID Architecture | PASS | Single Responsibility preserved — plugin still does one thing; the additional fields are pure data passthrough. No new coupling introduced. |
| P3 No Vendor Lock-in | N/A | No provider-specific code touched. |
| P4 Optimised Feedback Loops | PASS | New behaviour fully exercised by `tests/core/test_events.py` and `tests/plugins/test_ingest_website.py`; runs locally under `poetry run pytest`. |
| P5 Best Available Infrastructure | N/A | No CI/CD changes. |
| P6 Spec-Driven Development | PASS | This retrospec records the spec; the change qualified as a small bug fix under P6's exception clause but was promoted to a full SDD artifact set for traceability. |
| P7 No Filling Tests | PASS | Tests assert wire-format invariants (camelCase aliases, default values, propagation through three return paths) — each guards a real behavioural contract with the alkemio-server. |
| P8 Architecture Decision Records | N/A | No port/adapter, plugin contract, or deployment-model change. The change is a backward-compatible additive field on an existing event. |
| Microkernel Architecture | PASS | Change confined to `core/events/` (schema) and `plugins/ingest_website/` (handler). Core untouched, no cross-plugin coupling. |
| Plugin Contract | PASS | `PluginContract` protocol unchanged. |
| Event Schema as Wire Contract | PASS | Additive change with empty-string defaults; existing field names and types preserved. camelCase aliases applied (`bodyOfKnowledgeId`, `personaId`); `type` and `purpose` are already lowercase so no alias is required. |
| Domain Logic Isolation | N/A | Domain pipeline unchanged. |
| Async-First Design | PASS | No change to async semantics. |
| Simplicity Over Speculation | PASS | Minimal patch — four fields and three call-site updates. No abstractions introduced for the unused `bodyOfKnowledgeId` field; it is reserved by being present with an empty default. |

## Project Structure

### Documentation (this feature)

```text
specs/032-ingest-result-correlation/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
├── contracts/
│   └── ingest-website-result.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
core/
└── events/
    └── ingest_website.py          # Modified: 4 new fields on IngestWebsiteResult

plugins/
└── ingest_website/
    └── plugin.py                  # Modified: propagate fields from event in 3 return sites

tests/
├── core/
│   └── test_events.py             # Modified: default-value + explicit-value serialization tests
└── plugins/
    └── test_ingest_website.py     # Modified: propagation assertions on 2 plugin paths
```

**Structure Decision**: Standard microkernel layout. Changes live in `core/events/` (event schema is part of the wire contract) and `plugins/ingest_website/` (the only producer of `IngestWebsiteResult`). No new files. No directory or module-boundary changes.

## Complexity Tracking

No constitution violations — this section is not applicable.
