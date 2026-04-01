# Feature Specification: Unified Microkernel Virtual Contributor Engine

**Feature Branch**: `001-microkernel-engine-impl`
**Created**: 2026-03-30
**Status**: Draft
**Input**: User description: "implement the PRD in docs/PRD.md - the skeleton of the architecture is already scaffolded"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Core Message Processing (Priority: P1)

The Alkemio platform sends a question to a virtual contributor via RabbitMQ. The unified engine receives the message, identifies the correct handler based on the message content (engine type), and returns an AI-generated response in the same format the platform currently expects.

**Why this priority**: This is the foundational capability. Without core message routing and at least one working engine handler, nothing else functions. It validates that the plugin architecture, port abstractions, and message transport all work together end-to-end.

**Independent Test**: Can be fully tested by sending a well-formed RabbitMQ message with a known engine type (e.g., "generic") and verifying the system routes it to the correct handler and returns a valid response.

**Acceptance Scenarios**:

1. **Given** the engine is running with a configured plugin, **When** a valid message arrives on the plugin's RabbitMQ queue, **Then** the system routes the message to the correct plugin handler and publishes a response to the result queue.
2. **Given** the engine is running, **When** a message arrives for an unknown or unregistered plugin type, **Then** the system returns an error response indicating the engine type is not supported (does not crash or silently drop the message).
3. **Given** the engine receives a message, **When** the handler encounters an error during processing, **Then** the system returns a user-friendly error response and logs the failure (does not leave the message unacknowledged).

---

### User Story 2 - Engine Plugin Functionality (Priority: P2)

Each plugin type (expert, generic, guidance, openai-assistant) handles its specific interaction pattern correctly. The expert plugin executes prompt graphs with knowledge retrieval. The generic plugin makes direct LLM calls with optional history condensation. The guidance plugin performs multi-stage retrieval from multiple knowledge collections. The OpenAI assistant plugin manages threads and runs via the Assistants API.

**Why this priority**: These are the four active plugin types serving production traffic. Each must reproduce the exact behavior of its current standalone repository to maintain backward compatibility with the Alkemio platform.

**Independent Test**: Each plugin can be tested in isolation by sending it the same messages its current standalone counterpart receives and verifying identical response structure and content quality.

**Acceptance Scenarios**:

1. **Given** the expert plugin is loaded, **When** it receives an Input with a prompt_graph definition and body_of_knowledge_id, **Then** it executes the graph with knowledge retrieval and returns a response with source citations.
2. **Given** the generic plugin is loaded with chat history, **When** it receives a follow-up question, **Then** it condenses the history with the current question and returns a contextually relevant response.
3. **Given** the guidance plugin is loaded, **When** it receives a query, **Then** it retrieves context from its configured knowledge collections, filters by relevance score, and returns a response.
4. **Given** the openai-assistant plugin is loaded, **When** it receives a message with an assistant_id and thread_id, **Then** it creates or resumes the OpenAI thread, polls for completion, and returns the response with citation markers stripped.

---

### User Story 3 - Content Ingestion (Priority: P3)

The Alkemio platform triggers content ingestion for a website or a knowledge space. The engine crawls/fetches the content, chunks it, optionally summarizes it, generates embeddings, and stores the results in a vector database. The platform can then use this indexed knowledge for RAG-based virtual contributor responses.

**Why this priority**: Ingestion is the pipeline that feeds knowledge to the engine plugins. Without it, expert and guidance engines have no knowledge base to query. It depends on core ports being available (LLM, embeddings, knowledge store) but is independently deployable.

**Independent Test**: Can be tested by triggering a website ingestion for a known URL and verifying that documents appear in the vector store with correct metadata (documentId, source, type, title, chunkIndex).

**Acceptance Scenarios**:

1. **Given** the ingest-website plugin is loaded, **When** it receives an IngestWebsite event with a target URL, **Then** it crawls the site (respecting domain boundaries and page limits), chunks the content, generates embeddings, and stores them in the knowledge store.
2. **Given** the ingest-space plugin is loaded, **When** it receives an IngestBodyOfKnowledge event with a space identifier, **Then** it fetches the space tree via GraphQL, processes all callouts and attached files (PDF, DOCX, XLSX), and stores the indexed content in the knowledge store.
3. **Given** an ingestion is in progress, **When** the source content contains files in supported formats, **Then** the system extracts text from each format and includes it in the chunking and embedding pipeline.
4. **Given** a knowledge collection already exists for a source, **When** a re-ingestion is triggered, **Then** the previous collection is replaced with the fresh content (no stale data persists).

---

### User Story 4 - Single-Image Deployment (Priority: P4)

The DevOps team builds a single container image and deploys it as any virtual contributor variant by setting the PLUGIN_TYPE environment variable. Each container instance runs exactly one plugin, preserving the current process isolation model while eliminating the need to build and maintain 7+ separate images.

**Why this priority**: This eliminates the operational burden of 7 separate Docker images, 28 CI workflow files, and per-repo deployment pipelines. It is a major motivator for the consolidation but depends on the core and plugins being functional first.

**Independent Test**: Can be tested by building the image once, then launching separate containers with different PLUGIN_TYPE values and verifying each correctly handles its specific message type.

**Acceptance Scenarios**:

1. **Given** a single built container image, **When** it is started with `PLUGIN_TYPE=expert`, **Then** only the expert plugin is loaded and the container listens on the expert RabbitMQ queue.
2. **Given** a single built container image, **When** it is started with `PLUGIN_TYPE=ingest-website`, **Then** only the ingest-website plugin is loaded and the container listens on the ingest-website RabbitMQ queue.
3. **Given** a container is started with an invalid or missing PLUGIN_TYPE, **Then** the system fails fast with a clear error message indicating the available plugin types.

---

### User Story 5 - Plugin Extensibility (Priority: P5)

A developer adds a new virtual contributor type (e.g., libra-flow) by creating a new plugin directory with a handler that conforms to the plugin contract. The new plugin is automatically discovered by the registry without modifying core code, the router, or the container configuration.

**Why this priority**: This validates the microkernel architecture's key promise: extensibility without core modification. It is critical for future growth (libra-flow will be added later) but not required for the initial migration.

**Independent Test**: Can be tested by creating a minimal "echo" plugin that simply returns the input message and verifying it is discoverable and routable without any core changes.

**Acceptance Scenarios**:

1. **Given** a new plugin directory exists with a handler conforming to the plugin contract, **When** the engine starts, **Then** the registry discovers and registers the new plugin automatically.
2. **Given** a new plugin is registered, **When** a message arrives with the new plugin's event type, **Then** the router dispatches it to the new handler and returns its response.

---

### Edge Cases

- What happens when a plugin's required external service (LLM provider, vector DB) is temporarily unavailable? The adapter retries with exponential backoff (max 3 attempts), then returns an error response. The message is NACKed and redelivered; repeated failures route it to the dead-letter queue.
- What happens when a message is malformed or missing required fields? The system should reject it with a descriptive error, NACK the message, and let the dead-letter queue capture it for inspection (no infinite redelivery loops).
- What happens when the OpenAI assistant run times out (exceeds the configured poll timeout)? The system should return a timeout error response.
- What happens when website crawling encounters robots.txt restrictions or unreachable pages? The system should skip those pages and continue with available content.
- What happens when ingestion receives a file in an unsupported format? The system should skip the file, log a warning, and continue processing other content.
- What happens when a second ingestion request arrives for a source that is already being ingested? The system NACKs the duplicate with a "busy" error; the caller can retry after the in-progress ingestion completes.
- What happens when a plugin encounters an unrecoverable error (OOM, unhandled exception)? The container exits with a non-zero code; Kubernetes restart policy handles recovery.

## Clarifications

### Session 2026-03-30

- Q: When should RabbitMQ messages be acknowledged — before or after plugin processing? → A: ACK after processing with a dead-letter queue for repeated failures (at-least-once delivery + poison message protection).
- Q: Should the plugin contract include explicit lifecycle methods (startup/shutdown)? → A: Yes, add both `startup()` and `shutdown()` methods for resource init and graceful drain.
- Q: What should adapters do when an external service returns a transient error or times out? → A: Retry with exponential backoff (max 3 attempts, bounded delay) then fail with error response.
- Q: How should the system expose health status for Kubernetes probes? → A: Lightweight HTTP health endpoints (`/healthz` liveness, `/readyz` readiness) reflecting RabbitMQ connection and plugin readiness.
- Q: What logging format should the system use? → A: JSON structured logging with standard fields (timestamp, level, plugin_type, message, correlation_id).
- Q: Should "engine type" or "plugin type" be the canonical internal term? → A: "plugin" is canonical internally (code, logs, config); "engine" only appears in external RabbitMQ message field names for backward compatibility.
- Q: What happens when two ingestion requests for the same source arrive concurrently? → A: Reject duplicate — if ingestion is already running for a source, NACK the second request with a "busy" error.
- Q: Should plugins process messages sequentially or concurrently? → A: Sequential — one message at a time per plugin process (prefetch=1). Concurrency can be added later per-plugin if needed.
- Q: How should the container handle unrecoverable plugin errors (unhandled exceptions, OOM)? → A: Fail-fast — container exits with non-zero code and lets Kubernetes restart it.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST receive messages from RabbitMQ queues and dispatch them to the correct plugin based on message content (engine type or event type).
- **FR-002**: System MUST return responses in the exact same format (JSON structure, field names, camelCase aliases) as the current standalone services to maintain backward compatibility with the Alkemio platform.
- **FR-003**: System MUST support loading exactly one plugin per process instance, determined by a configuration value at startup.
- **FR-004**: System MUST provide LLM invocation capabilities to plugins that need it, supporting at minimum Mistral and OpenAI providers.
- **FR-005**: System MUST provide text embedding capabilities to plugins that need it, supporting at minimum Scaleway and OpenAI embedding providers.
- **FR-006**: System MUST provide vector database query and storage capabilities to plugins that need it.
- **FR-007**: System MUST support the prompt graph execution pattern used by the expert plugin (graph-defined LLM workflows with special node injection and streaming).
- **FR-008**: System MUST support the OpenAI Assistants API interaction pattern (thread management, run polling, file attachment) used by the openai-assistant plugin.
- **FR-009**: System MUST support content ingestion from websites via recursive crawling with domain boundary enforcement, URL filtering, and configurable page limits.
- **FR-010**: System MUST support content ingestion from Alkemio spaces via GraphQL queries, including recursive space tree traversal and file parsing (PDF, DOCX, XLSX).
- **FR-011**: System MUST implement a shared content processing pipeline: chunking (configurable size/overlap), optional summarization, embedding generation, and batch storage in a vector database.
- **FR-012**: System MUST use the same RabbitMQ queue names, exchange names, and routing keys as the current standalone services.
- **FR-022**: System MUST process messages sequentially (RabbitMQ prefetch=1). Each plugin instance handles one message at a time; horizontal scaling is achieved by running additional container replicas.
- **FR-023**: System MUST fail-fast on unrecoverable errors (unhandled exceptions, OOM). The container MUST exit with a non-zero code and rely on Kubernetes restart policies for recovery. No internal restart or reinitialization logic.
- **FR-016**: System MUST acknowledge RabbitMQ messages only after successful plugin processing (at-least-once delivery semantics). Messages that fail processing repeatedly MUST be routed to a dead-letter queue to prevent infinite redelivery loops (poison message protection).
- **FR-017**: Plugin contract MUST include `startup()` and `shutdown()` lifecycle methods. The core MUST call `startup()` after dependency injection and before message consumption, and `shutdown()` on SIGTERM/SIGINT to allow graceful drain of in-flight work.
- **FR-018**: Adapters for external services (LLM, embeddings, knowledge store, GraphQL API) MUST implement retry with exponential backoff (max 3 attempts, bounded delay) for transient errors before returning a failure. Permanent errors (4xx, auth failures) MUST fail immediately without retry.
- **FR-019**: System MUST expose HTTP health endpoints: `/healthz` (liveness — process is running) and `/readyz` (readiness — RabbitMQ connected and plugin startup completed). These endpoints are used by Kubernetes liveness and readiness probes.
- **FR-020**: System MUST use JSON structured logging with standard fields: `timestamp`, `level`, `plugin_type`, `message`, and `correlation_id` (derived from the RabbitMQ message ID or correlation header). All log entries across core and plugins MUST use this format for consistent log aggregation.
- **FR-013**: System MUST support all configuration via environment variables, maintaining compatibility with existing Kubernetes secrets and configmaps.
- **FR-014**: System MUST allow plugins to declare which infrastructure dependencies they require rather than mandating all dependencies for all plugins.
- **FR-021**: Ingestion plugins MUST reject concurrent requests for the same source (same URL or same space identifier). If ingestion is already in progress for a source, the duplicate message MUST be NACKed with a "busy" error so the caller can retry later.
- **FR-015**: System MUST authenticate with the Alkemio platform (via Kratos) for the ingest-space plugin to access the GraphQL API.

### Key Entities

- **Plugin**: A self-contained handler for a specific virtual contributor type. Declares its name, the event type it handles, and the infrastructure ports it requires. Implements lifecycle methods: `startup()` for resource initialization and `shutdown()` for graceful teardown (draining in-flight work, releasing connections). Each plugin runs as the sole handler in a process.
- **Port**: A technology-agnostic interface defining a capability (LLM invocation, embedding, knowledge storage, message transport). Plugins depend on ports, never on concrete implementations.
- **Adapter**: A concrete implementation of a port for a specific technology (e.g., Mistral for LLM, ChromaDB for knowledge storage). Registered at startup and injected into plugins.
- **Event**: A message received from or sent to the Alkemio platform via RabbitMQ. Types include Input (engine queries), IngestWebsite, IngestBodyOfKnowledge, and Response.
- **Plugin Registry**: Maintains the mapping between plugin names/event types and their handler implementations. Supports runtime discovery of plugins.
- **Content-Based Router**: Examines incoming messages to determine which registered plugin should handle them based on event type and engine type fields.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All 7 public repositories' functionality is reproduced — each plugin type produces responses indistinguishable from its standalone predecessor when given the same input.
- **SC-002**: A single container image can be deployed as any of the 6 plugin types (expert, generic, guidance, openai-assistant, ingest-website, ingest-space) by changing one configuration value.
- **SC-003**: Core system test coverage reaches at least 80% (up from 0% in the current base engine).
- **SC-004**: Existing tests from expert, openai-assistant, and ingest-website repositories pass after being ported to the unified structure.
- **SC-005**: The total number of CI workflow files is reduced by at least 75% (from 28 to 7 or fewer).
- **SC-006**: Adding a new plugin type requires zero modifications to core system code — only a new plugin directory and handler.
- **SC-007**: Message contract compatibility is preserved — the Alkemio platform sends the same RabbitMQ messages and receives the same response format without any platform-side changes.

## Assumptions

- The scaffolded directory structure (`core/`, `plugins/`, `tests/`) is the target layout and should be built upon, not restructured.
- Python 3.12 is the target runtime for all plugins, including those currently on Python 3.11 (guidance, generic) and TypeScript (ingest-space).
- The existing base engine library (`alkemio-virtual-contributor-engine`) will be decomposed into the `core/` module rather than used as an external dependency.
- The `pyproject.toml` with Poetry dependency management is the chosen packaging approach.
- RabbitMQ message contracts (queue names, exchange names, event schemas with camelCase aliases) must remain exactly the same to ensure zero-downtime migration.
- Each container runs exactly one plugin — multi-plugin-per-process is not a requirement.
- The private `libra-flow` repository is explicitly out of scope and will be added as a plugin after this consolidation is validated.
- The archived `community-manager` repository requires no action.
- External services (RabbitMQ, ChromaDB, LLM providers, Alkemio GraphQL API) are available in the deployment environment — the system does not need to provide them.
- Plugins may require different subsets of ports — not every plugin needs LLM, embeddings, and knowledge store capabilities.
- **Terminology convention**: "plugin" is the canonical internal term (code, config, logs, documentation). "Engine type" appears only in external RabbitMQ message field names (`engine_type`) for backward compatibility with the Alkemio platform.
