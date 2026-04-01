# Implementation Plan: Multi-Provider LLM Support

**Branch**: `002-multi-provider-llm` | **Date**: 2026-04-01 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-multi-provider-llm/spec.md`

## Summary

Make the virtual-contributor engine provider-agnostic so any LLM provider (Mistral, OpenAI-compatible, Anthropic) can be used by changing environment variables only — no code changes. The implementation introduces a **provider factory** that resolves the correct LangChain `BaseChatModel` adapter from configuration, a unified adapter wrapper implementing `LLMPort`, per-provider and per-plugin configuration via environment variables, and robust structured output parsing that normalises JSON extraction across providers.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: langchain ^1.1.0, langchain-openai ^1.1.0, langchain-mistralai ^1.1.0, langchain-anthropic (NEW — to add), langgraph ^1.0.4, pydantic ^2.11, pydantic-settings ^2.11.0, aio-pika 9.5.7
**Storage**: ChromaDB (vector store via chromadb-client ^1.5.0), RabbitMQ (message transport)
**Testing**: pytest (async tests with mock ports)
**Target Platform**: Linux server (Docker containers, K8s orchestrated)
**Project Type**: Microkernel message-processing service
**Performance Goals**: N/A — existing latency profile maintained; LLM call latency is provider-dominated
**Constraints**: Single global LLM timeout; async-first; identical RabbitMQ response envelope format regardless of provider
**Scale/Scope**: 6 plugins × 3+ providers; single container per plugin instance

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| P1 AI-Native Development | ✅ PASS | Feature designed for autonomous delivery via SDD workflow |
| P2 SOLID Architecture | ✅ PASS | **S**: Factory is single-purpose. **O**: New providers added without modifying core/plugins. **L**: All LLM adapters interchangeable via `LLMPort`. **I**: Plugins declare only ports they need. **D**: Plugins depend on `LLMPort`, never on concrete adapters. |
| P3 No Vendor Lock-in | ✅ PASS | This feature **implements** P3 — provider selection becomes a configuration concern |
| P4 Optimised Feedback Loops | ✅ PASS | Tests must cover: factory resolution, per-provider adapter construction, structured output parsing, config validation, fail-fast on bad provider. Non-deterministic LLM tests for each provider. |
| P5 Best Available Infrastructure | ✅ PASS | No CI changes required |
| P6 Spec-Driven Development | ✅ PASS | Following SDD workflow now |
| P7 No Filling Tests | ✅ PASS | Tests will guard behavioural contracts: correct provider resolution, structured output parsing edge cases, config validation errors |
| P8 Architecture Decision Records | ⚠️ REQUIRED | ADR needed: "Use LangChain BaseChatModel abstraction with unified adapter wrapper for multi-provider LLM support" — this introduces a new adapter pattern and new dependency |
| **Microkernel Architecture** | ✅ PASS | Core provides provider factory; plugins unaffected |
| **Hexagonal Boundaries** | ✅ PASS | `LLMPort` interface unchanged; new adapters in `core/adapters/` |
| **Plugin Contract** | ✅ PASS | No changes to `PluginContract` |
| **Event Schema** | ✅ PASS | No changes to event models |
| **Domain Logic Isolation** | ✅ PASS | `PromptGraph` receives LLM via parameter; unaffected |
| **Single Image, Multiple Deployments** | ✅ PASS | Same image; provider selected by env vars at startup |
| **Async-First Design** | ✅ PASS | All LangChain adapters use `ainvoke`/`astream` |
| **Simplicity Over Speculation** | ✅ PASS | No speculative abstractions — factory resolves one provider per config |

**Gate result: PASS** — one ADR required (tracked as implementation task).

## Project Structure

### Documentation (this feature)

```text
specs/002-multi-provider-llm/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── llm-port.md      # LLMPort interface contract (unchanged)
│   └── provider-config.md # Provider configuration contract
└── tasks.md             # Phase 2 output (NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
core/
├── ports/
│   └── llm.py                  # LLMPort Protocol (UNCHANGED)
├── adapters/
│   ├── mistral.py              # REMOVE — replaced by unified adapter
│   ├── openai_llm.py           # REMOVE — replaced by unified adapter
│   ├── langchain_llm.py        # NEW — unified LangChain LLM adapter
│   └── openai_assistant.py     # UNCHANGED (not a generic LLM adapter)
├── config.py                   # MODIFY — add provider config fields
├── container.py                # UNCHANGED
└── provider_factory.py         # NEW — resolves provider from config

plugins/                        # UNCHANGED — no plugin code changes
tests/
├── core/
│   ├── test_provider_factory.py   # NEW
│   ├── test_langchain_llm.py      # NEW
│   └── test_config_validation.py  # NEW (provider config edge cases)
└── plugins/                    # UNCHANGED
```

**Structure Decision**: Follows existing microkernel layout. New files are a unified LLM adapter (`core/adapters/langchain_llm.py`) and a provider factory (`core/provider_factory.py`). The two existing per-provider adapters (`mistral.py`, `openai_llm.py`) are consolidated into the unified adapter since they share identical logic — only the LangChain model class differs.

## Constitution Re-Check (Post Phase 1 Design)

| Principle | Status | Post-Design Notes |
|-----------|--------|-------------------|
| P2 SOLID — Open/Closed | ✅ PASS | Confirmed: adding a 4th provider requires only a new entry in the factory dict + a `pyproject.toml` dependency. No core/plugin changes. |
| P2 SOLID — Liskov | ✅ PASS | Confirmed: `LangChainLLMAdapter` wraps any `BaseChatModel`. All providers pass the same `LLMPort` protocol. |
| P3 No Vendor Lock-in | ✅ PASS | Confirmed: provider is selected by env var; adapter substitution is transparent to plugins. |
| P8 ADR Required | ⚠️ PENDING | ADR must be created during implementation: "0005 — Unified LangChain adapter with provider factory for multi-provider LLM support" |
| Hexagonal Boundaries | ✅ PASS | Confirmed: `LLMPort` unchanged. New adapter in `core/adapters/`. Factory in `core/` (internal wiring). |
| Simplicity | ✅ PASS | Confirmed: factory is a single function (~40 LOC). Unified adapter is ~60 LOC. No class hierarchies or registries. |

**Post-design gate: PASS**

## Complexity Tracking

> No constitution violations requiring justification. The design is straightforward.
