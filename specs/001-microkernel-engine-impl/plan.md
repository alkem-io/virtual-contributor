# Implementation Plan: Unified Microkernel Virtual Contributor Engine

**Branch**: `001-microkernel-engine-impl` | **Date**: 2026-03-30 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-microkernel-engine-impl/spec.md`

## Summary

Consolidate 7 public Alkemio virtual-contributor repositories into a single unified repository using a **Microkernel Architecture** with **Hexagonal (Ports and Adapters)** internal structure. The core system provides plugin registry, content-based message routing, IoC container, and event schemas. Six plugin components (expert, generic, guidance, openai-assistant, ingest-website, ingest-space) implement domain-specific logic behind a stable Plugin Contract protocol. External dependencies (LLM, embeddings, vector DB, message transport) are accessed through technology-agnostic port interfaces with swappable adapter implementations. A single Docker image serves all plugins, selected at container start via `PLUGIN_TYPE` environment variable.

## Technical Context

**Language/Version**: Python 3.12 (unified from mixed 3.11/3.12/TypeScript)
**Primary Dependencies**: aio-pika 9.5.7 (async RabbitMQ), pydantic ^2.11 (validation + settings), langchain ^1.1.0 + langgraph ^1.0.4 (LLM orchestration + graph workflows), openai ^1.109 (OpenAI SDK), chromadb-client ^1.5.0 (vector DB), httpx ^0.27.2 (HTTP), beautifulsoup4 ^4.14 (HTML parsing)
**Storage**: ChromaDB (vector database for knowledge store — embeddings, document chunks, metadata)
**Testing**: pytest ^9.0 + pytest-asyncio ^1.3 (async test support) + pytest-cov ^7.1 (coverage reporting)
**Target Platform**: Linux containers on Kubernetes (single Docker image, one plugin per container)
**Project Type**: Async message-driven microkernel service (RabbitMQ consumer/publisher)
**Performance Goals**: Sequential message processing per plugin instance (prefetch=1). Horizontal scaling via Kubernetes replica count. No latency SLA — bounded by upstream LLM/embedding provider response times.
**Constraints**: Backward-compatible RabbitMQ wire contracts (queue names, exchange names, event schemas with camelCase aliases). At-least-once delivery with dead-letter queue. Plugin LOC budget: 30-300 unique LOC (hard limit ~500). One plugin per process.
**Scale/Scope**: 6 plugin types replacing 7 public repositories. ~460 LOC unique engine logic + ~1,292 LOC base engine to be decomposed into core/. ingest-space is a TypeScript-to-Python port (~3K LOC custom logic).

## Constitution Check (Pre-Design)

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Core Principles

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| P1 | AI-Native Development | PASS | Following SDD workflow (spec → plan → tasks → impl). Tooling targets autonomous agent execution. |
| P2 | SOLID Architecture | PASS | **S**: one plugin = one event type. **O**: new plugins without core changes. **L**: adapters swappable behind ports. **I**: plugins declare only needed ports. **D**: plugins depend on port protocols, never concrete adapters. |
| P3 | No Vendor Lock-in | PASS | LLM/embedding providers behind port interfaces. OpenAI Assistant exception documented in spec (wraps fundamentally different Assistants API interaction model). |
| P4 | Optimised Feedback Loops | PASS | pytest + pytest-asyncio for testing. Pre-commit hooks must mirror CI checks. Local-first feedback. |
| P5 | Best Available Infrastructure | DEFERRED | CI/CD infrastructure decisions deferred to Phase 4 (infrastructure). Not blocking for design. |
| P6 | Spec-Driven Development | PASS | Actively following: spec (done) → plan (this document) → tasks → implementation. |
| P7 | No Filling Tests | PASS | Test strategy: port contract tests, adapter integration tests, plugin behavior tests, edge case tests. No coverage-only tests. |
| P8 | ADR | ACTION NEEDED | `docs/adr/` directory must be created. ADRs needed: (1) Microkernel + Hexagonal architecture, (2) TypeScript-to-Python port decision, (3) Plugin contract design, (4) Sequential processing model. ADRs will be written during implementation per the principle's "before or at the time of implementation" rule. |

### Architecture Standards

| Standard | Status | Notes |
|----------|--------|-------|
| Microkernel Architecture | PASS | `core/` (core system) + `plugins/` (plugin components) + registry + router |
| Hexagonal Boundaries | PASS | `core/ports/` (driven port interfaces) + `core/adapters/` (driven adapter implementations) |
| Plugin Contract | PASS | `PluginContract` Protocol class with `name`, `event_type`, `startup()`, `shutdown()`, `handle()` |
| Event Schema | PASS | Pydantic models with `by_alias=True` serialization, camelCase wire format |
| Domain Logic Isolation | PASS | `core/domain/` for ingest pipeline, PromptGraph, summarization — composes ports, testable with mocks |
| Single Image | PASS | Single Dockerfile, `PLUGIN_TYPE` env var, matrix CI strategy |
| Async-First | PASS | `aio-pika` with `prefetch=1`, all handlers `async def`, port interfaces define `async` methods for I/O |
| Simplicity | PASS | Plugin LOC targets: expert ~60, generic ~30, guidance ~50, openai-assistant ~70. Core domain: ingest_pipeline, prompt_graph, summarize_graph |

**Gate Result**: PASS (P8 ADR action is a concurrent obligation, not a blocker — ADRs will be written during implementation)

## Project Structure

### Documentation (this feature)

```text
specs/001-microkernel-engine-impl/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── rabbitmq-events.md   # RabbitMQ message schemas (wire contract)
│   ├── health-endpoints.md  # HTTP health check endpoints
│   └── plugin-contract.md   # Plugin Protocol interface
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
virtual-contributor/
├── core/
│   ├── __init__.py
│   ├── ports/                       # Driven (Secondary) Port interfaces
│   │   ├── __init__.py
│   │   ├── llm.py                   # LLMPort Protocol — chat model invocation
│   │   ├── embeddings.py            # EmbeddingsPort Protocol — text embedding
│   │   ├── knowledge_store.py       # KnowledgeStorePort Protocol — vector DB ops
│   │   └── transport.py             # TransportPort Protocol — message consume/publish
│   ├── adapters/                    # Driven (Secondary) Adapter implementations
│   │   ├── __init__.py
│   │   ├── mistral.py               # Mistral LLM adapter (langchain-mistralai)
│   │   ├── openai_llm.py            # OpenAI ChatCompletion adapter (langchain-openai)
│   │   ├── openai_assistant.py      # OpenAI Assistants API adapter (openai SDK)
│   │   ├── chromadb.py              # ChromaDB knowledge store adapter
│   │   ├── rabbitmq.py              # RabbitMQ transport adapter (aio-pika)
│   │   ├── scaleway_embeddings.py   # Scaleway embeddings adapter
│   │   └── openai_embeddings.py     # OpenAI embeddings adapter
│   ├── domain/                      # Internal shared logic
│   │   ├── __init__.py
│   │   ├── ingest_pipeline.py       # chunk → summarize → embed → store
│   │   ├── summarize_graph.py       # LangGraph summarize-then-refine
│   │   └── prompt_graph.py          # PromptGraph execution engine
│   ├── events/                      # Pydantic message schemas
│   │   ├── __init__.py
│   │   ├── base.py                  # Base event model
│   │   ├── input.py                 # Input, HistoryItem, RoomDetails, ExternalConfig
│   │   ├── response.py              # Response with sources
│   │   ├── ingest_website.py        # IngestWebsite event
│   │   └── ingest_space.py          # IngestBodyOfKnowledge event
│   ├── config.py                    # BaseConfig (Pydantic Settings)
│   ├── container.py                 # IoC Container — adapter registration/resolution
│   ├── health.py                    # Async HTTP health server (/healthz, /readyz)
│   ├── logging.py                   # JSON structured logging (FR-020)
│   ├── registry.py                  # Plugin Registry (Microkernel)
│   └── router.py                    # Content-Based Router (EIP)
│
├── plugins/
│   ├── __init__.py
│   ├── expert/
│   │   ├── __init__.py
│   │   ├── plugin.py                # ExpertPlugin — PromptGraph + knowledge retrieval
│   │   └── prompts.py               # Expert-specific prompt templates
│   ├── generic/
│   │   ├── __init__.py
│   │   ├── plugin.py                # GenericPlugin — direct LLM with history condensation
│   │   └── prompts.py               # Generic prompt templates
│   ├── guidance/
│   │   ├── __init__.py
│   │   ├── plugin.py                # GuidancePlugin — multi-collection RAG
│   │   └── prompts.py               # Guidance prompt templates
│   ├── openai_assistant/
│   │   ├── __init__.py
│   │   ├── plugin.py                # OpenAIAssistantPlugin — threads/runs/files
│   │   └── utils.py                 # Citation stripping, thread management
│   ├── ingest_space/
│   │   ├── __init__.py
│   │   ├── plugin.py                # IngestSpacePlugin — RabbitMQ handler
│   │   ├── graphql_client.py        # Alkemio GraphQL queries + Kratos auth
│   │   ├── space_reader.py          # Recursive space tree traversal
│   │   └── file_parsers.py          # PDF, DOCX, XLSX text extraction
│   └── ingest_website/
│       ├── __init__.py
│       ├── plugin.py                # IngestWebsitePlugin — RabbitMQ handler
│       ├── crawler.py               # Recursive web crawling + URL filtering
│       └── html_parser.py           # BeautifulSoup content extraction
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                  # Shared fixtures: mock ports, test events
│   ├── core/
│   │   ├── __init__.py
│   │   ├── test_registry.py         # Plugin discovery and registration
│   │   ├── test_router.py           # Content-based message routing
│   │   ├── test_container.py        # IoC container resolution
│   │   ├── test_events.py           # Event model serialization (camelCase)
│   │   └── domain/
│   │       ├── __init__.py
│   │       ├── test_ingest_pipeline.py
│   │       ├── test_prompt_graph.py
│   │       └── test_summarize_graph.py
│   └── plugins/
│       ├── __init__.py
│       ├── test_expert.py           # Ported from engine-expert tests
│       ├── test_generic.py
│       ├── test_guidance.py
│       ├── test_openai_assistant.py # Ported from engine-openai-assistant tests
│       ├── test_ingest_website.py   # Ported from ingest-website tests (90% coverage)
│       └── test_ingest_space.py
│
├── docs/
│   ├── PRD.md
│   └── adr/                         # Architecture Decision Records
│       ├── 0001-microkernel-hexagonal-architecture.md
│       ├── 0002-typescript-to-python-port.md
│       ├── 0003-plugin-contract-design.md
│       └── 0004-sequential-processing-model.md
│
├── main.py                          # Single entry point
├── Dockerfile                       # Multi-stage, PLUGIN_TYPE selects at runtime
├── docker-compose.yaml              # All services from one image
├── pyproject.toml                   # Poetry config (already exists)
├── .flake8                          # Linting config (already exists)
└── .github/workflows/               # Matrix-based CI/CD (~5 files)
```

**Structure Decision**: Microkernel layout with `core/` (core system) and `plugins/` (plugin components) at repository root. This matches the scaffolded directory structure already in place. The `tests/` directory mirrors the source layout with `core/` and `plugins/` subdirectories.

## Constitution Check (Post-Design)

*Re-evaluated after Phase 1 design artifacts are complete.*

### Core Principles

| # | Principle | Status | Post-Design Notes |
|---|-----------|--------|-------------------|
| P1 | AI-Native Development | PASS | SDD workflow progressing: spec (done) → plan (done) → tasks (next) → impl. |
| P2 | SOLID Architecture | PASS | Design confirms: **S** — each plugin has one event type + handler. **O** — plugin-contract.md confirms new plugins need zero core changes. **L** — data-model.md defines swappable adapters behind port protocols. **I** — plugin-to-port mapping in contract shows each plugin declares only needed ports. **D** — plugin constructor injection documented, no adapter imports allowed. |
| P3 | No Vendor Lock-in | PASS | Port interfaces (LLMPort, EmbeddingsPort, KnowledgeStorePort) defined in data-model.md. OpenAI Assistant exception justified in Complexity Tracking below. |
| P4 | Optimised Feedback Loops | PASS | Test strategy in research.md: 3 layers (core, domain, plugin), ported tests from 3 repos, non-deterministic LLM test approach defined. Pre-commit + CI parity required. |
| P5 | Best Available Infrastructure | DEFERRED | CI/CD infrastructure decisions remain deferred to implementation phase. |
| P6 | Spec-Driven Development | PASS | Full SDD artifact chain: spec.md → plan.md → research.md → data-model.md → contracts/ → quickstart.md. |
| P7 | No Filling Tests | PASS | research.md §3 defines meaningful test categories: port contract compliance, adapter integration, plugin behavior, edge cases. No coverage-only tests. |
| P8 | ADR | ACTION NEEDED | 4 ADRs identified in pre-design check. Will be written during implementation. |

### Architecture Standards

| Standard | Status | Post-Design Notes |
|----------|--------|-------------------|
| Microkernel Architecture | PASS | data-model.md §4 entity relationships confirm clean core/plugin separation. |
| Hexagonal Boundaries | PASS | 4 port protocols + 7 adapters defined in data-model.md §2.2. Dependency rule enforced via protocol typing. |
| Plugin Contract | PASS | Fully specified in contracts/plugin-contract.md: name, event_type, startup(), shutdown(), handle(). |
| Event Schema | PASS | contracts/rabbitmq-events.md defines all wire schemas with camelCase aliases. Contract tests specified. |
| Domain Logic Isolation | PASS | data-model.md §3 defines Document, IngestResult, PromptGraph, QueryResult as domain objects in core/domain/. They compose ports via DI, testable with mocks. |
| Single Image | PASS | quickstart.md confirms single Dockerfile, PLUGIN_TYPE selection. research.md §4.1 details build stages. |
| Async-First | PASS | All port methods are `async def`. TransportPort, LLMPort, EmbeddingsPort, KnowledgeStorePort are async. |
| Simplicity | PASS | Plugin LOC targets confirmed: expert ~60, generic ~30, guidance ~50, openai-assistant ~70. No speculative abstractions. |

**Post-Design Gate Result**: PASS — No new violations introduced. P8 ADR obligation carried forward to implementation.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| OpenAI Assistant uses direct SDK, not LLM port | Assistants API (threads/runs/files) is fundamentally different from chat completion — cannot be abstracted behind the generic LLMPort | Forcing it behind LLMPort would create a leaky abstraction requiring thread_id, assistant_id, and polling semantics that don't map to `invoke(messages)` |
| ingest-space requires Kratos authentication | Must authenticate with Alkemio platform to access private GraphQL API | Unauthenticated access not possible for private space data |
