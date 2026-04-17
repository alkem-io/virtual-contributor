# Implementation Plan: Pipeline Reliability and BoK Resilience

**Branch**: `story/020-pipeline-reliability` | **Date**: 2026-04-15 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/020-pipeline-reliability/spec.md`

## Summary

Fix an async deadlock caused by zombie threads from timed-out LLM calls, prevent orphaned background tasks in DocumentSummaryStep, and make BoK summarization resilient with partial fallback, section grouping, and inline persistence. Additionally fix an embeddings truthiness bug in ChangeDetectionStep and add batch-level deduplication in StoreStep.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: asyncio, concurrent.futures, langchain-core
**Storage**: ChromaDB (unchanged schema)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: Eliminate thread pool deadlocks; reduce BoK refinement rounds by 60-75% via section grouping
**Constraints**: All BodyOfKnowledgeSummaryStep constructor changes are additive (backward-compatible defaults)
**Scale/Scope**: 6 files modified, ~120 lines added, ~15 lines removed; 1 test file updated

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | All changes are deterministic fixes to async patterns, no interactive steps |
| P2 | SOLID Architecture | PASS | BoKStep constructor changes are additive with defaults (Open/Closed). No new interfaces. Inline persist is an optimization of existing responsibilities, not a new concern |
| P3 | No Vendor Lock-in | PASS | No provider-specific changes. ThreadPoolExecutor is stdlib |
| P4 | Optimised Feedback Loops | PASS | Tests updated for BoK skip behavior with store interaction. Partial summary failure tested. Debug logging added per refinement round |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD artifacts in specs/020-pipeline-reliability/ |
| P7 | No Filling Tests | PASS | BoK skip test validates real store interaction (pre-populates MockKnowledgeStorePort with BoK entry, asserts skip behavior). Not a trivial assertion |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Changes confined to core domain and adapters. No cross-plugin coupling |
| AS:Hexagonal | Hexagonal Boundaries | PASS | BoKStep receives ports via constructor (DI). No adapter leaks into domain |
| AS:Plugin | Plugin Contract | PASS | PluginContract unchanged. Plugin changes are limited to passing ports to steps |
| AS:Domain | Domain Logic Isolation | PASS | Pipeline step protocol unchanged. Behavior changes are within step implementations |
| AS:Simplicity | Simplicity Over Speculation | PASS | Each fix targets a specific observed failure mode. No speculative abstractions. Thread pool size matches workload math (8 concurrent summarizations x 3 retries + headroom) |
| AS:Async | Async-First Design | PASS | Fixes three async anti-patterns: retry-on-timeout with zombie threads, orphaned background tasks, unbounded default thread pool |

**Gate result**: PASS -- no violations.

## Project Structure

### Documentation (this feature)

```text
specs/020-pipeline-reliability/
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
├── adapters/
│   └── langchain_llm.py       # Remove timeout retry, raise TimeoutError immediately
└── domain/
    └── pipeline/
        └── steps.py            # _refine_summarize partial fallback, DocumentSummaryStep try/finally,
                                # BoKStep section grouping + inline persist + _bok_exists,
                                # StoreStep batch dedup, ChangeDetection embeddings fix

main.py                         # Explicit ThreadPoolExecutor(max_workers=32)

plugins/
├── ingest_space/
│   └── plugin.py               # Pass embeddings_port + knowledge_store_port to BoKStep
└── ingest_website/
    └── plugin.py               # Pass embeddings_port + knowledge_store_port to BoKStep

tests/
└── core/
    └── domain/
        └── test_pipeline_steps.py  # Updated BoK skip test with MockKnowledgeStorePort
```

## Complexity Tracking

No constitution violations to justify.
