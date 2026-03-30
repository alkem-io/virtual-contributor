<!--
  SYNC IMPACT REPORT
  Version change: 1.0.0 → 2.0.0 (MAJOR)

  Restructure: Old principles 1–10 were a mix of governance principles
  and architecture standards. This revision separates them:
    - Core Principles (§1): 8 governance-level principles (user-defined)
    - Architecture Standards (§2): technical enforcement rules
      (incorporates old P1–P5, P7–P10 as standards, not principles)

  New principles:
    - P1 "AI-Native Development"
    - P2 "SOLID Architecture"
    - P3 "No Vendor Lock-in" (absorbs old P8 "Provider Agnosticism")
    - P4 "Optimised Feedback Loops" (absorbs old P6 testing philosophy)
    - P5 "Best Available Infrastructure"
    - P6 "Spec-Driven Development (SDD)"
    - P7 "No Filling Tests" (absorbs old P6 testing standards)
    - P8 "Architecture Decision Records (ADR)"

  Old principles demoted to Architecture Standards:
    - P1 "Microkernel Architecture Integrity"
    - P2 "Hexagonal Boundaries (Ports and Adapters)"
    - P3 "Plugin Contract as Stable Interface"
    - P4 "Event Schema as Wire Contract"
    - P5 "Domain Logic Isolation"
    - P7 "Single Image, Multiple Deployments"
    - P9 "Async-First Design"
    - P10 "Simplicity Over Speculation"

  Removed (superseded):
    - P6 "Code Quality with Pragmatic Testing" → P4 + P7
    - P8 "Provider Agnosticism" → P3

  Templates:
    - .specify/templates/plan-template.md       — ✅ no update needed
    - .specify/templates/spec-template.md       — ✅ no update needed
    - .specify/templates/tasks-template.md      — ⚠ pending: line 11
      states "Tests are OPTIONAL" which conflicts with P4 and P7
    - .specify/templates/checklist-template.md  — ✅ no update needed

  Follow-up TODOs:
    - Update tasks-template.md to remove "Tests are OPTIONAL" guidance
-->
# Alkemio Virtual Contributor Engineering Constitution

## Core Principles

### 1. AI-Native Development

This repository is designed for **AI-native development** with the
fastest possible feedback loops. Most features MUST be designed for
**zero human interaction** in the delivery cycle — from specification
through implementation, testing, and merge. Tooling, CI/CD, and workflow
configuration MUST prioritise autonomous agent execution. Human
intervention is reserved for architectural decisions, principle
amendments, and exception handling.

### 2. SOLID Architecture

The repository adheres to **SOLID principles**, mapped to the Microkernel
+ Hexagonal architecture defined in the Architecture Standards section:

- **Single Responsibility (S)**: Each plugin does exactly one thing. Each
  port interface has exactly one purpose. A plugin that handles more than
  one event type or a port that bundles unrelated operations MUST be
  split.
- **Open/Closed (O)**: New plugins and adapters are added without
  modifying the core (`core/`). The plugin registry, port interfaces, and
  router MUST remain stable when extending the system.
- **Liskov Substitution (L)**: Any adapter implementing a port (e.g.,
  `LLMPort`) MUST be interchangeable — Mistral, OpenAI, or any future
  provider — without altering plugin behaviour. Substituting one adapter
  for another MUST NOT require plugin code changes.
- **Interface Segregation (I)**: Plugins declare only the ports they
  need. There MUST NOT be a god-interface that bundles all ports. Each
  plugin receives its specific dependencies via constructor injection.
- **Dependency Inversion (D)**: Plugins depend on port interfaces
  (`core/ports/`), never on concrete adapters (`core/adapters/`). A
  plugin that imports `from core.adapters.* import ...` MUST be rejected
  at review. Source code dependencies point inward only.

### 3. No Vendor Lock-in

LLM and embedding providers are implementation details behind port
interfaces. The system MUST support switching providers (e.g., Mistral →
OpenAI, Scaleway → another embedding service) with **adapter-level
changes only** — no plugin code modifications. Provider selection is a
configuration concern resolved by the IoC container from environment
variables or per-request `external_config`. No plugin logic MUST be
tightly coupled to a specific vendor. Exception: the OpenAI Assistant
plugin inherently depends on the OpenAI Assistants API as it wraps a
fundamentally different interaction model (threads/runs/files), not a
generic chat completion.

### 4. Optimised Feedback Loops

Feedback loops MUST be maximal, optimised, and **local-first**:

- **Test coverage**: Maximise meaningful test coverage across all layers
  — core ports/adapters, domain logic, and plugin behaviour.
- **Deterministic tests**: Standard unit and integration tests with
  predictable, reproducible assertions.
- **Non-deterministic tests**: LLM response tests MUST verify behavioural
  properties (e.g., temperature > 0 produces varied responses; responses
  contain expected semantic content). These tests validate the stochastic
  nature of LLM outputs and MUST be included alongside deterministic
  tests.
- **Local before remote**: Developers and agents MUST get feedback
  locally before CI/CD. Pre-commit hooks are **mandatory** and MUST
  execute the same linting, formatting, and test checks that run in CI
  builds. There MUST be no check that passes locally but fails in CI, or
  vice versa.
- **CI/CD mirrors local**: The CI pipeline MUST NOT introduce checks
  absent from the local pre-commit workflow. Parity between local and
  remote feedback is non-negotiable.

### 5. Best Available Infrastructure

CI/CD builds MUST use the **best infrastructure available** in the
Alkemio organisation to maximise automated feedback loop speed. The
specific runner type, instance class, or hardware generation is an
implementation detail that changes over time (currently M4 self-hosted
runners). When superior infrastructure becomes available, builds MUST
migrate promptly. Build performance is a first-class concern — slow
builds degrade the feedback loop and violate Principle 4.

### 6. Spec-Driven Development (SDD)

**Spec-Driven Development is mandatory** for all feature development.
Every feature MUST progress through the SDD workflow: specification →
plan → tasks → implementation. This ensures traceability from
requirements to delivered code and enables AI-native autonomous delivery
(Principle 1). Small-scale bug fixes (isolated, single-file changes with
clear root cause) MAY bypass SDD, but any fix that touches multiple
modules or introduces new behaviour MUST follow the full workflow.

### 7. No Filling Tests

All tests MUST test **meaningful code paths**. Tests that exist solely to
inflate coverage metrics — testing trivial getters/setters, re-asserting
framework guarantees, or exercising code paths with no meaningful
assertion — are forbidden. Edge cases MUST be tested explicitly. Every
test MUST have a clear reason for existence: it either guards a
behavioural contract, validates a boundary condition, or prevents a
documented regression.

### 8. Architecture Decision Records (ADR)

All major architectural decisions MUST be recorded as **Architecture
Decision Records**. An ADR captures the context, decision, alternatives
considered, and consequences. A decision is "major" if it affects port
interfaces, introduces or removes an adapter, changes the plugin
contract, alters the deployment model, or selects a new external
dependency. ADRs MUST be written **before or at the time** of
implementation, not retroactively. They live in `docs/adr/` and follow
sequential numbering (`0001-*.md`, `0002-*.md`, ...). ADRs are immutable
once accepted — superseding decisions create new ADRs that reference the
old ones.

## Architecture Standards

### Microkernel Architecture

The system follows the **Microkernel Architecture** pattern
(Richards/Ford). The **Core System** (`core/`) provides the minimal
runtime: plugin registry, content-based message routing, IoC container,
and event schemas. All domain-specific logic MUST reside in **Plugin
Components** (`plugins/`). The core MUST NOT contain logic specific to
any single plugin. Plugins MUST NOT depend on each other — only on the
core's published contracts. Any change that introduces cross-plugin
coupling MUST refactor before merge.

### Hexagonal Boundaries (Ports and Adapters)

External dependencies are accessed through **Ports** (technology-agnostic
interfaces defined in `core/ports/`) with concrete **Adapters**
(technology-specific implementations in `core/adapters/`). Per Cockburn's
Hexagonal Architecture:

- **Driven (Secondary) Ports**: LLM, Embeddings, KnowledgeStore,
  Transport — interfaces the application calls outward.
- **Driven (Secondary) Adapters**: Mistral, OpenAI, ChromaDB, RabbitMQ,
  Scaleway — concrete implementations.
- **Driving (Primary) Adapter**: RabbitMQ consumer that delivers messages
  into the core.

Plugins receive port interfaces via **Constructor Injection** (Fowler),
never via direct adapter imports. The **Dependency Rule** (Clean
Architecture): source code dependencies point inward only — plugins
depend on ports, adapters implement ports, neither knows about the other.

### Plugin Contract

The **Plugin Contract** (`PluginContract` protocol) is the stable
interface between core and plugins. It defines: plugin name, event type,
and async handle method with injected port dependencies. Changes to the
contract are **breaking** and require a constitution version bump with
migration notes and an ADR (Principle 8). All plugins MUST be
runtime-checkable against the contract. New plugins MUST include:
contract implementation, at least one meaningful test (Principle 7), and
a configuration section in the README.

### Event Schema as Wire Contract

Event models (`core/events/`) define the RabbitMQ message contract with
the Alkemio server. Field names use **camelCase aliases** for wire format
compatibility. Changes to event schemas MUST maintain backward
compatibility with the existing Alkemio server. Breaking changes require
coordinated server + virtual-contributor releases and an ADR
(Principle 8). All events MUST use Pydantic models with explicit field
validation.

### Domain Logic Isolation

Shared domain logic in `core/domain/` (ingest pipeline, summarization
graphs, PromptGraph execution) is internal to the core — not a port, not
an adapter. It composes ports but lives inside the application boundary.
Domain functions MUST accept port interfaces as parameters (dependency
injection), not import adapters directly. This logic is testable in
isolation with mock ports.

### Single Image, Multiple Deployments

One Docker image serves all plugins. The `PLUGIN_TYPE` environment
variable selects which plugin to activate at container start. Each plugin
runs in its own container for process isolation. The Dockerfile MUST be
parameterized, not duplicated. GitHub Actions workflows use **matrix
strategy** — not copy-pasted per-plugin files. K8s manifests are
parameterized templates.

### Async-First Design

All message handling is async (`async/await`). RabbitMQ consumers use
`aio-pika` with `prefetch=1` for sequential per-queue processing. Port
interfaces define async methods where I/O is involved. Synchronous
blocking calls in the message handling path are forbidden.

### Simplicity Over Speculation

Prefer the simplest implementation that satisfies the plugin contract. Do
not add configuration, abstractions, or extension points "in case we need
them later." Each engine plugin MUST remain small (30–300 LOC of unique
logic). If a plugin grows beyond ~500 LOC of unique logic, evaluate
whether it MUST be decomposed or whether shared domain logic MUST be
extracted to `core/domain/`.

### Technical Rules

1. **Directory Layout**:
   - `core/ports/*`: technology-agnostic interfaces (Driven Ports)
   - `core/adapters/*`: technology-specific implementations
   - `core/domain/*`: shared internal logic
   - `core/events/*`: Pydantic message schemas
   - `core/container.py`: IoC container
   - `core/registry.py`: Plugin Registry
   - `core/router.py`: Content-Based Router
   - `plugins/*/plugin.py`: Plugin Contract implementations
   - `docs/adr/*`: Architecture Decision Records (Principle 8)
2. All port interfaces MUST be Python `Protocol` classes (structural
   subtyping, no inheritance required).
3. Adapter selection is driven by environment variables, resolved at
   container startup, not at import time.
4. Event models MUST use `by_alias=True` for serialization (camelCase
   wire format).
5. One `main.py` entry point loads the plugin registry, resolves
   adapters, and starts the transport consumer.

## Engineering Workflow

1. All feature work MUST follow the SDD workflow (Principle 6):
   specification → plan → tasks → implementation.
2. Pre-commit hooks MUST run linting, formatting, and tests
   (Principle 4). The hook configuration MUST mirror CI checks exactly.
3. Major architectural decisions MUST produce an ADR (Principle 8)
   before or at the time of implementation.
4. PRs MUST state: which plugins are affected, any port/contract changes,
   event schema changes.
5. New plugin: provide `plugin.py`, meaningful tests (Principle 7),
   update README, add to CI matrix.
6. Port interface changes: update all affected adapters and plugin tests.
7. Adapter additions: implement the full port interface, provide
   integration test or mock test.
8. CI builds MUST run on the best available infrastructure (Principle 5).
9. Migration from old repos: maintain exact same RabbitMQ queue names and
   event schemas for backward compatibility.

## Governance

Amendments require: proposal PR referencing impacted principles,
rationale, and version bump classification. Semantic versioning of this
constitution:

- MAJOR: Removal or redefinition of a principle.
- MINOR: Addition of a new principle or architecture standard.
- PATCH: Clarifications without behavioral change.

Compliance Review:

- Constitution Check section in planning MUST reference any intentional
  deviations.
- Unjustified violations block merge.
- Deprecated items tracked until removal executed.

Enforcement:

- Pre-commit hooks enforce linting, formatting, and test execution
  (Principle 4).
- CI pipelines enforce the same checks as pre-commit hooks.
- Automated lint / CI may enforce module boundaries and port/adapter
  separation.
- Manual review ensures plugin isolation, SOLID compliance (Principle 2),
  and testing adequacy (Principles 4, 7).

**Version**: 2.0.0 | **Ratified**: 2026-03-30 | **Last Amended**: 2026-03-30
