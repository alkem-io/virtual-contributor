# Alkemio Virtual Contributor Engineering Constitution

## Core Principles

### 1. Microkernel Architecture Integrity

The system follows the **Microkernel Architecture** pattern (Richards/Ford). The **Core System** (`core/`) provides the minimal runtime: plugin registry, content-based message routing, IoC container, and event schemas. All domain-specific logic MUST reside in **Plugin Components** (`plugins/`). The core MUST NOT contain logic specific to any single plugin. Plugins MUST NOT depend on each other — only on the core's published contracts. Any change that introduces cross-plugin coupling MUST refactor before merge.

### 2. Hexagonal Boundaries (Ports and Adapters)

External dependencies are accessed through **Ports** (technology-agnostic interfaces defined in `core/ports/`) with concrete **Adapters** (technology-specific implementations in `core/adapters/`). Per Cockburn's Hexagonal Architecture:

- **Driven (Secondary) Ports**: LLM, Embeddings, KnowledgeStore, Transport — interfaces the application calls outward.
- **Driven (Secondary) Adapters**: Mistral, OpenAI, ChromaDB, RabbitMQ, Scaleway — concrete implementations.
- **Driving (Primary) Adapter**: RabbitMQ consumer that delivers messages into the core.

Plugins receive port interfaces via **Constructor Injection** (Fowler), never via direct adapter imports. A plugin that imports `from core.adapters.mistral import ...` MUST be rejected at review. The **Dependency Rule** (Clean Architecture): source code dependencies point inward only — plugins depend on ports, adapters implement ports, neither knows about the other.

### 3. Plugin Contract as Stable Interface

The **Plugin Contract** (`PluginContract` protocol) is the stable interface between core and plugins. It defines: plugin name, event type, and async handle method with injected port dependencies. Changes to the contract are **breaking** and require a version bump with migration notes. All plugins MUST be runtime-checkable against the contract. New plugins MUST include: contract implementation, at least one test, and a configuration section in the README.

### 4. Event Schema as Wire Contract

Event models (`core/events/`) define the RabbitMQ message contract with the Alkemio server. Field names use **camelCase aliases** for wire format compatibility. Changes to event schemas MUST maintain backward compatibility with the existing Alkemio server. Breaking changes require coordinated server + virtual-contributor releases. All events MUST use Pydantic models with explicit field validation.

### 5. Domain Logic Isolation

Shared domain logic in `core/domain/` (ingest pipeline, summarization graphs, PromptGraph execution) is internal to the core — not a port, not an adapter. It composes ports but lives inside the application boundary. Domain functions MUST accept port interfaces as parameters (dependency injection), not import adapters directly. This logic is testable in isolation with mock ports.

### 6. Code Quality with Pragmatic Testing

Tests defend behavioral contracts and port boundaries. Use a risk-based approach:
- **Core ports/adapters**: require comprehensive tests — these are the foundation everything depends on.
- **Plugin logic**: test the unique business logic, not the boilerplate injection.
- **Domain logic**: test chunking, summarization, graph execution independently of adapters.

100% coverage is NOT required. Tests MUST stay maintainable and purposeful. The previous base engine had **zero tests** — that gap MUST NOT be repeated. Minimum core coverage target: **80%**.

### 7. Single Image, Multiple Deployments

One Docker image serves all plugins. The `PLUGIN_TYPE` environment variable selects which plugin to activate at container start. Each plugin runs in its own container for process isolation. The Dockerfile MUST be parameterized, not duplicated. GitHub Actions workflows use **matrix strategy** — not copy-pasted per-plugin files. K8s manifests are parameterized templates.

### 8. Provider Agnosticism

LLM and embedding providers are implementation details behind port interfaces. No plugin logic should be tightly coupled to a specific vendor (Mistral, OpenAI, Scaleway). Provider selection is a **configuration concern** resolved by the IoC container from env vars or per-request `external_config`. Exception: the OpenAI Assistant plugin inherently depends on the OpenAI Assistants API — this is acceptable as it wraps a fundamentally different interaction model (threads/runs/files), not a generic chat completion.

### 9. Async-First Design

All message handling is async (`async/await`). RabbitMQ consumers use `aio-pika` with `prefetch=1` for sequential per-queue processing. Port interfaces define async methods where I/O is involved. Synchronous blocking calls in the message handling path are forbidden.

### 10. Simplicity Over Speculation

Prefer the simplest implementation that satisfies the plugin contract. Do not add configuration, abstractions, or extension points "in case we need them later." Each engine plugin should remain small (30-300 LOC of unique logic). If a plugin grows beyond ~500 LOC of unique logic, evaluate whether it should be decomposed or whether shared domain logic should be extracted to `core/domain/`.

## Architecture Standards

1. Directory Layout:
   - `core/ports/*`: technology-agnostic interfaces (Driven Ports)
   - `core/adapters/*`: technology-specific implementations (Driven Adapters)
   - `core/domain/*`: shared internal logic (ingest pipeline, summarization, PromptGraph)
   - `core/events/*`: Pydantic message schemas (wire contract with Alkemio server)
   - `core/container.py`: IoC container — registers adapters, resolves ports
   - `core/registry.py`: Plugin Registry — maps plugin names to implementations
   - `core/router.py`: Content-Based Router — dispatches messages to plugins
   - `plugins/*/plugin.py`: Plugin Contract implementations
2. All port interfaces MUST be Python `Protocol` classes (structural subtyping, no inheritance required).
3. Adapter selection is driven by environment variables, resolved at container startup, not at import time.
4. Event models MUST use `by_alias=True` for serialization (camelCase wire format).
5. One `main.py` entry point loads the plugin registry, resolves adapters, and starts the transport consumer.

## Engineering Workflow

1. PRs MUST state: which plugins are affected, any port/contract changes, event schema changes.
2. New plugin: provide plugin.py, at least one test, update README, add to CI matrix.
3. Port interface changes: update all affected adapters and plugin tests.
4. Adapter additions: implement the full port interface, provide integration test or mock test.
5. Migration from old repos: maintain exact same RabbitMQ queue names and event schemas for backward compatibility.

## Governance

Amendments require: proposal PR referencing impacted principles, rationale, and version bump classification. Semantic versioning of this constitution:

- MAJOR: Removal or redefinition of a principle.
- MINOR: Addition of a new principle or architecture standard.
- PATCH: Clarifications without behavioral change.

Compliance Review:

- Constitution Check section in planning MUST reference any intentional deviations.
- Unjustified violations block merge.
- Deprecated items tracked until removal executed.

Enforcement:

- Automated lint / CI may enforce module boundaries and port/adapter separation.
- Manual review ensures plugin isolation & testing adequacy.

**Version**: 1.0.0 | **Ratified**: 2026-03-30
