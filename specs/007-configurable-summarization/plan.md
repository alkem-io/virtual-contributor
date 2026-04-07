# Implementation Plan: Configurable Pipeline — Separate Summarization LLM and Externalized Retrieval Parameters

**Branch**: `007-configurable-summarization` | **Date**: 2026-04-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-configurable-summarization/spec.md`

## Summary

Add a separate, configurable LLM for summarization tasks (document + body-of-knowledge) to reduce ingestion costs by 5-10x, externalize retrieval parameters (per-plugin `n_results`, score thresholds, context budget) as environment variables for production tuning, and make the summarization chunk threshold configurable. All changes are additive to `core/config.py`, `main.py`, and the relevant plugins, with full backward compatibility when new env vars are unset.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langchain-anthropic ^0.3, langgraph ^1.0.4, pydantic ^2.11, pydantic-settings ^2.11.0, aio-pika 9.5.7, chromadb-client ^1.5.0, httpx ^0.27.2
**Storage**: ChromaDB (vector store via HTTP client), RabbitMQ (message transport)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service (plugins selected via PLUGIN_TYPE env var)
**Performance Goals**: N/A (configuration change, no new throughput requirements)
**Constraints**: Full backward compatibility (FR-009); no port/adapter interface changes
**Scale/Scope**: 6 plugins, ~6,500 LOC; changes touch core/config.py, main.py, 4 plugins

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Following SDD workflow; feature is config-only, no interactive steps |
| P2 | SOLID Architecture | PASS | No new port interfaces. Summarization LLM reuses existing `LLMPort`. Per-plugin config uses existing injection pattern. Open/Closed satisfied — no core modifications beyond config fields |
| P3 | No Vendor Lock-in | PASS | Summarization LLM uses same provider-agnostic factory (`create_llm_adapter`). All 3 providers (Mistral, OpenAI, Anthropic) supported |
| P4 | Optimised Feedback Loops | PASS | Tests required for: config validation, summarization LLM fallback, per-plugin retrieval injection, context budget enforcement |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Full SDD workflow in progress |
| P7 | No Filling Tests | PASS | Each test guards a behavioral contract: config validation, fallback logic, budget truncation |
| P8 | ADR | PASS | No port/contract/adapter changes. No new external dependencies. No ADR required |
| AS:Microkernel | Microkernel Architecture | PASS | Config stays in core. No cross-plugin coupling. Ingest plugins receive summarization LLM via constructor injection |
| AS:Hexagonal | Hexagonal Boundaries | PASS | Summarization LLM is another `LLMPort` instance — same port, same adapter, different config |
| AS:Plugin | Plugin Contract | PASS | `PluginContract` unchanged. Ingest plugins gain an optional `summarize_llm` constructor parameter |
| AS:Domain | Domain Logic Isolation | PASS | `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` already accept `llm_port` as constructor arg — no change to domain logic |
| AS:Simplicity | Simplicity Over Speculation | PASS | Minimal additions: config fields + wiring. No new abstractions |
| AS:Async | Async-First Design | PASS | No new sync calls. All LLM invocations remain async |

**Gate result**: PASS — no violations. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/007-configurable-summarization/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
core/
├── config.py              # Add summarization LLM fields, per-plugin retrieval fields,
│                          # context budget, chunk threshold
├── provider_factory.py    # No changes (reused as-is for summarization LLM)
├── container.py           # No changes
├── ports/
│   └── llm.py             # No changes (reused as-is)
├── adapters/
│   └── langchain_llm.py   # No changes
└── domain/
    └── pipeline/
        └── steps.py       # DocumentSummaryStep: accept configurable chunk threshold
                           # Both summary steps: add model/token logging (FR-011)

plugins/
├── expert/
│   └── plugin.py          # Accept per-plugin n_results/score_threshold (already does)
│                          # Add MAX_CONTEXT_CHARS enforcement
├── guidance/
│   └── plugin.py          # Accept configurable n_results (currently hardcoded to 5)
│                          # Add MAX_CONTEXT_CHARS enforcement
├── ingest_website/
│   └── plugin.py          # Accept optional summarize_llm, pass to summary steps
└── ingest_space/
    └── plugin.py          # Accept optional summarize_llm, pass to summary steps

main.py                    # Wire summarization LLM adapter; inject per-plugin retrieval config

tests/
├── test_config_summarize_llm.py    # Config validation for summarization LLM
├── test_config_retrieval.py        # Config validation for per-plugin retrieval params
├── test_context_budget.py          # MAX_CONTEXT_CHARS enforcement logic
└── test_summarize_threshold.py     # SUMMARY_CHUNK_THRESHOLD behavior

.env.example               # Document all new variables (FR-010)
```

**Structure Decision**: Single project layout (existing). All changes are additive to existing files. No new directories or modules needed beyond test files.

## Complexity Tracking

No constitution violations to justify.
