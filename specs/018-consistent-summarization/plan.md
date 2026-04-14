# Implementation Plan: Consistent Summarization Behavior Between Ingest Plugins

**Branch**: `story/1827-consistent-summarization-behavior` | **Date**: 2026-04-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/018-consistent-summarization/spec.md`

## Summary

Add a `summarize_enabled` boolean config flag to explicitly control whether summarization steps are included in ingest pipelines, treat `summarize_concurrency=0` as sequential execution (not disabled), and remove the inline `BaseConfig()` instantiation from ingest-website so both plugins use constructor injection consistently. All changes are backward compatible.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: pydantic-settings ^2.11.0
**Storage**: ChromaDB (unchanged)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: N/A (configuration and pipeline construction change)
**Constraints**: Full backward compatibility; no port interface changes
**Scale/Scope**: 5 files modified, ~40 lines added, ~10 lines removed

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Config + wiring change, no interactive steps |
| P2 | SOLID Architecture | PASS | No new port interfaces. Plugins gain constructor params (Open/Closed). Inline config removed (Dependency Inversion) |
| P3 | No Vendor Lock-in | PASS | No provider-specific changes |
| P4 | Optimised Feedback Loops | PASS | Config validation catches invalid values at startup. New tests cover all scenarios |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts in specs/018-consistent-summarization/ |
| P7 | No Filling Tests | PASS | All tests guard meaningful behavioral contracts (pipeline composition under different configs) |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Config stays in core. No cross-plugin coupling |
| AS:Hexagonal | Hexagonal Boundaries | PASS | Removing inline BaseConfig() from ingest-website improves hexagonal compliance |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged. Constructor params are optional with defaults |
| AS:Domain | Domain Logic Isolation | PASS | IngestEngine, PipelineStep protocol unchanged. Changes are in plugin pipeline construction |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal change: one config field, one validation, constructor injection, conditional step inclusion |
| AS:Async | Async-First Design | PASS | No new sync calls |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/018-consistent-summarization/
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
└── config.py              # Add summarize_enabled field + concurrency validation

main.py                    # Inject summarize_enabled and summarize_concurrency into plugins

plugins/
├── ingest_space/
│   └── plugin.py          # Accept summarize_enabled + summarize_concurrency, conditional step inclusion
└── ingest_website/
    └── plugin.py          # Accept summarize_enabled + summarize_concurrency, remove inline BaseConfig(), conditional step inclusion

tests/
├── core/
│   └── test_config_validation.py  # Test concurrency validation + summarize_enabled defaults
└── plugins/
    ├── test_ingest_space.py       # Three-scenario summarization tests
    └── test_ingest_website.py     # Three-scenario summarization tests
```

## Complexity Tracking

No constitution violations to justify.
