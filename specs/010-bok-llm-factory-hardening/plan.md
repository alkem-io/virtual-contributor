# Implementation Plan: BoK LLM, Summarize Base URL, and LLM Factory Hardening

**Branch**: `develop` | **Date**: 2026-04-08 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/010-bok-llm-factory-hardening/spec.md`

## Summary

Add a third LLM tier for body-of-knowledge summarization (large-context-window model), support base URL overrides for the summarization LLM, and harden the LLM factory for local model backends. The BoK LLM falls back to the summarize LLM, then to the main LLM. The factory gains a `disable_thinking` parameter for Qwen3 models and restricts httpx keep-alive patching to the Mistral provider. All changes are additive with full backward compatibility.

## Technical Context

**Language/Version**: Python 3.12 (Poetry)
**Primary Dependencies**: langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langchain-anthropic ^0.3, pydantic-settings ^2.11.0
**Storage**: ChromaDB (unchanged)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (asyncio_mode = auto)
**Target Platform**: Linux server (Docker containers, K8s)
**Project Type**: Microkernel service
**Performance Goals**: N/A (configuration and wiring change)
**Constraints**: Full backward compatibility; no port interface changes
**Scale/Scope**: 6 files modified, ~85 lines added

## Constitution Check

| # | Principle / Standard | Status | Notes |
|---|---------------------|--------|-------|
| P1 | AI-Native Development | PASS | Config + wiring change, no interactive steps |
| P2 | SOLID Architecture | PASS | No new port interfaces. BoK LLM reuses existing `LLMPort`. Ingest plugins gain an optional constructor param — Open/Closed satisfied |
| P3 | No Vendor Lock-in | PASS | BoK LLM uses same provider-agnostic factory. All 3 providers supported. Factory hardening improves multi-provider support |
| P4 | Optimised Feedback Loops | PASS | Config validation catches invalid values at startup |
| P5 | Best Available Infrastructure | N/A | No CI changes |
| P6 | SDD | PASS | Retrospec in progress |
| P7 | No Filling Tests | N/A | No tests added in this changeset |
| P8 | ADR | PASS | No port/contract changes. No new external dependencies |
| AS:Microkernel | Microkernel Architecture | PASS | Config stays in core. No cross-plugin coupling. Ingest plugins receive BoK LLM via constructor injection |
| AS:Hexagonal | Hexagonal Boundaries | PASS | BoK LLM is another `LLMPort` instance — same port, same adapter, different config |
| AS:Plugin | Plugin Contract | PASS | `PluginContract` unchanged. Ingest plugins gain optional `bok_llm` constructor param |
| AS:Domain | Domain Logic Isolation | PASS | `BodyOfKnowledgeSummaryStep` already accepts `llm_port` — no domain change needed |
| AS:Simplicity | Simplicity Over Speculation | PASS | Reuses existing patterns: synthetic config + create_llm_adapter. Factory param is minimal |
| AS:Async | Async-First Design | PASS | No new sync calls |

**Gate result**: PASS — no violations.

## Project Structure

### Documentation (this feature)

```text
specs/010-bok-llm-factory-hardening/
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
├── config.py              # Add bok_llm_* fields (6) + summarize_llm_base_url
└── provider_factory.py    # Add disable_thinking param; Mistral-only keepalive; tighter hasattr

main.py                    # BoK LLM creation/wiring/logging; summarize base_url; disable_thinking

plugins/
├── ingest_space/
│   └── plugin.py          # Accept optional bok_llm, route to BodyOfKnowledgeSummaryStep
└── ingest_website/
    └── plugin.py          # Accept optional bok_llm, route to BodyOfKnowledgeSummaryStep

.env.example               # Document BOK_LLM_* and SUMMARIZE_LLM_BASE_URL
```

## Complexity Tracking

No constitution violations to justify.
