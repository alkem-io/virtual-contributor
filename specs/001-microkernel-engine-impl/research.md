# Research: Unified Microkernel Virtual Contributor Engine

**Feature**: 001-microkernel-engine-impl
**Date**: 2026-03-30
**Sources**: PRD analysis, source repository code review (verified 2026-03-30), existing test suites

## 1. Source Repository Implementation Analysis

### 1.1 Base Engine (virtual-contributor-engine)

**Decision**: Decompose the base engine library into `core/` modules rather than use it as an external dependency.

**Rationale**: The base engine has fundamental design limitations that prevent clean plugin architecture: single handler registration, module-level singleton initialization, hardcoded if/else routing, and mandatory ChromaDB import at load time. Breaking it apart into ports, adapters, domain logic, and events allows proper inversion of control.

**Alternatives considered**:
- Keep as external PyPI dependency → Rejected: cannot fix the singleton model, import-time side effects, or single-handler limitation without rewriting it anyway
- Fork and modify → Rejected: creates a maintenance fork; cleaner to decompose into purpose-built modules

**Key modules to decompose**:
| Base Engine Module | Target Location | LOC | Notes |
|---|---|---|---|
| `alkemio_vc_engine.py` (109 LOC) | `core/registry.py` + `core/router.py` + `main.py` | Split into plugin registry, content-based router, and entry point |
| `rabbitmq.py` (126 LOC) | `core/adapters/rabbitmq.py` | Async aio-pika wrapper, prefetch=1 pattern preserved |
| `config.py` (83 LOC) | `core/config.py` | Pydantic Settings for env vars |
| `models.py` (27 LOC) | Eliminated | Module-level singletons replaced by IoC container adapter resolution |
| `prompt_graph/` (368 LOC) | `core/domain/prompt_graph.py` | LangGraph-based graph execution preserved as-is |
| `chromadb_utils.py` (136 LOC) | `core/adapters/chromadb.py` | `query_documents()`, `ingest_documents()`, `combine_query_results()` become adapter methods |
| `events/` (197 LOC) | `core/events/` | Pydantic models with camelCase aliases — wire format preserved exactly |

### 1.2 Engine Plugins — Current Implementations

#### Expert Plugin (~60 LOC unique)
- Compiles a `PromptGraph` from `input.prompt_graph` JSON definition
- Injects a custom `retrieve` special node that queries ChromaDB collection `{bodyOfKnowledgeId}-knowledge`
- Streams execution via `graph.stream(input_state, stream_mode="updates")`
- Initial state includes: `messages`, `current_question`, `conversation`, `bok_id`, `description`, `display_name`
- Assembles response from graph output: `final_answer`, `knowledge_answer`, language fields, source scores
- **Three prompt templates**: `combined_expert_prompt` (RAG with `{vc_name}`, `{knowledge}`, `{question}`), `evaluation_prompt` (translates between context/knowledge answers), `input_checker_prompt` (analyzes conversation for follow-up detection)
- **Ports needed**: LLMPort (Mistral Small), KnowledgeStorePort (ChromaDB query)
- **Input fields used**: `prompt_graph` (required), `body_of_knowledge_id`, `description`, `display_name`, `persona_id`

#### Generic Plugin (~30 LOC unique)
- Uses `get_model(input.engine, input.external_config.api_key)` to select LLM provider per-request (maps `"generic-openai"` → `ChatOpenAI(model="gpt-4o")`)
- If chat history exists: condenser LLM call with `condenser_system_prompt` + `history_as_text(history)` rephrases current question
- System messages from `input.prompt` (list of strings) → `SystemMessage` objects
- Final invocation: `model.invoke([system_messages..., HumanMessage(content=question)])`
- No knowledge retrieval, no embeddings
- **Ports needed**: LLMPort (configurable — accepts `engine` and `api_key` from `input.external_config`)
- **Input fields used**: `engine`, `external_config.api_key`, `prompt` (system messages)
- **Note**: LLM provider selection is per-request via `external_config`, not per-deployment

#### Guidance Plugin (~50 LOC unique)
- Multi-stage: condense history → retrieve context from 3 ChromaDB collections → LLM response
- Parses JSON response from LLM to extract source scores
- Filters documents by relevance score
- **Ports needed**: LLMPort (Mistral Medium), KnowledgeStorePort (ChromaDB — queries 3 collections)
- **Input fields used**: `language`, `message`
- **Note**: Uses Python 3.11 + base engine v0.7.0 (stale). Has hardcoded collection names (`alkem.io-knowledge`, `welcome.alkem.io-knowledge`, `www.alkemio.org-knowledge`) that should become configurable

#### OpenAI Assistant Plugin (~70 LOC unique)
- Creates `AsyncOpenAI` client per-request using `input.external_config.api_key`
- If `input.external_metadata.thread_id` exists: retrieves existing thread, adds message
- Otherwise: creates new thread with initial message
- Lists and attaches all user files (via `client.files.list()`) with `file_search` tool
- Creates a run and polls status with 1s interval, configurable timeout (300s default, `RUN_POLL_TIMEOUT_SECONDS`)
- Extracts text from `TextContentBlock`, strips citation annotations
- Returns `Response(result=answer, thread_id=thread.id)` — thread_id in response enables conversation continuity
- **Ports needed**: OpenAI client (direct SDK — Assistants API with threads/runs/files)
- **Input fields used**: `external_config.assistant_id`, `external_config.api_key`, `external_metadata.thread_id`
- **Architectural note**: This plugin's LLM interaction is fundamentally different from chat completion. It uses OpenAI's managed Assistants API, not the generic LLMPort. Requires a separate `OpenAIAssistantAdapter`.

### 1.3 Ingest Plugins — Current Implementations

#### Ingest Website (~300 LOC unique)
- Recursive web crawler with domain boundary enforcement
- URL normalization, file-link filtering (65+ extensions)
- HTML content extraction from semantic tags (`p`, `section`, `article`, `h1`, `title`)
- Progressive length budgeting for summarization (40% → 100% scaling)
- Two-tier summarization: per-document + body-of-knowledge aggregate
- Configurable page limit (default 20, `PROCESS_PAGES_LIMIT`)
- **Ports needed**: LLMPort (Mistral Small), EmbeddingsPort (Scaleway Qwen3), KnowledgeStorePort (ChromaDB ingest)
- **Tests**: 862 LOC, 90% coverage enforced in CI

#### Ingest Space (TypeScript → Python port, ~3K LOC custom)
- Consumes `IngestBodyOfKnowledge` events from RabbitMQ (direct amqplib, not base engine)
- Authenticates via `@alkemio/client-lib` + Kratos
- Fetches space trees or knowledge bases via GraphQL (recursive 3-level hierarchy)
- Processes callouts: posts, whiteboards, link collections
- Downloads and parses files: PDF (pdf-parse), DOCX (mammoth), XLSX (xlsx), ODT (officeparser)
- Chunks with RecursiveCharacterTextSplitter (1000 chars, 100 overlap)
- Summarizes with LangGraph (Azure Mistral) — summarize-then-refine pattern
- Embeds with Azure OpenAI, upserts to ChromaDB in batches of 20
- Metadata schema: `documentId`, `source`, `type`, `title`, `embeddingType`, `chunkIndex`
- **Python equivalents for TS file parsers**: `pypdf` (PDF), `python-docx` (DOCX), `openpyxl` (XLSX)
- **Note**: 19.8K LOC of generated GraphQL types can be replaced with lightweight `httpx` GraphQL client

### 1.4 Wire Contract Corrections (Source Code vs PRD)

Source code review revealed several differences from the PRD's descriptions that are critical for backward compatibility:

| Area | PRD/Spec Assumption | Actual (Verified) | Impact |
|------|--------------------|--------------------|--------|
| Response field name | `body` | `result` | Breaking if wrong — must use `result` |
| Response extra fields | None | `human_language`, `result_language`, `knowledge_language`, `original_result`, `thread_id` | Must include all fields |
| HistoryItem role enum | `"user"` / `"assistant"` | `"human"` / `"assistant"` | Breaking if wrong |
| Input extra fields | Minimal | `operation`, `context_id`, `persona_id`, `result_handler` | Must deserialize all |
| ExternalConfig fields | `api_key`, `assistant_id`, `engine` | `api_key`, `assistant_id`, `model` (not `engine`) | Field name matters |
| IngestWebsite URL field | `url` | `base_url` (alias `baseUrl`) | Breaking if wrong |
| IngestWebsite extra fields | `space_id`, `body_of_knowledge_id` | `purpose`, `persona_id`, `summarization_model` | Different schema entirely |
| IngestWebsiteResult | `result`, `message` | `timestamp`, `result` (enum), `error` (string) | Different schema |
| Exchange type | topic (assumed) | DIRECT | Must use ExchangeType.DIRECT |
| Ingest-space queue | `virtual-contributor-ingest-space` | `virtual-contributor-ingest-body-of-knowledge` | Must use exact name |
| Ingest-space routing key | `ingest-space-result` | `IngestSpaceResult` (PascalCase) | Case-sensitive |
| Ingest-website result queue | Shared result queue | `virtual-contributor-ingest-website-result` (separate) | Separate per ingest type |
| Message envelope | Flat JSON | Queries: `{"input": {...}}`. Ingest: `{"eventType": "...", ...flat fields}` | Parsing logic must handle both |
| Published response | `{Response fields}` | `{"response": {...}, "original": {...}}` | Must wrap in envelope |
| ChromaDB default port | 8000 | 8765 | Config default matters |
| Guidance LLM model | mistral_small | mistral_medium | Different model |
| Source model | `uri`, `title`, `score` | `chunk_index`, `embedding_type`, `document_id`, `source`, `title`, `type`, `score`, `uri` | Much richer schema |
| IngestBodyOfKnowledge | `space_id`, `body_of_knowledge_id`, `type`, `space_name_id` | `body_of_knowledge_id`, `type` (enum), `purpose` (enum), `persona_id` | Different fields |
| ResultHandler | Not in PRD | Required field with `action` enum and `room_details` | New entity to model |
| ingest-space ACK model | Manual ACK (assumed) | `noAck: true` in TypeScript | Python port should use manual ACK per FR-016 |

**Action**: All event models, contracts, and data-model have been updated to match the verified source code.

## 2. Technology Decisions

### 2.1 Plugin Discovery and Registration

**Decision**: Import-based discovery with a plugin registry. Each plugin directory contains a `plugin.py` with a class implementing `PluginContract`. The registry scans `plugins/` at startup, imports the module for the configured `PLUGIN_TYPE`, and registers the handler.

**Rationale**: Simple, explicit, and debuggable. The system only loads one plugin per process, so dynamic discovery of all plugins is unnecessary. The `PLUGIN_TYPE` env var determines which single plugin module to import.

**Alternatives considered**:
- `importlib.metadata` entry points → Rejected: overengineered for single-plugin-per-process model. Entry points are useful when discovering plugins across installed packages, not within a single repo.
- Directory scanning with `__init__.py` exports → Rejected: would import all plugins at startup, loading unnecessary dependencies.
- Plugin manifest file (JSON/YAML) → Rejected: adds a file to maintain that duplicates information already in the plugin class.

### 2.2 IoC Container Design

**Decision**: Lightweight custom container using a dictionary mapping port protocols to adapter instances. No third-party DI framework.

**Rationale**: The system has a small, fixed set of ports (4: LLM, Embeddings, KnowledgeStore, Transport). A full DI framework (dependency-injector, inject, etc.) adds complexity without proportional benefit. The container resolves adapters at startup based on env vars and injects them into the plugin via constructor.

**Alternatives considered**:
- `dependency-injector` library → Rejected: heavyweight for 4 port bindings. Adds learning curve and config ceremony.
- Service Locator pattern → Rejected: violates DI principle (Fowler). Plugins should receive dependencies, not look them up.
- No container, manual wiring in main.py → Rejected: works for 1 plugin but becomes unmaintainable if adapter selection logic grows.

### 2.3 RabbitMQ Transport Pattern

**Decision**: Preserve the existing aio-pika pattern from the base engine: `prefetch=1`, exclusive reply queues, JSON serialization with camelCase aliases, dead-letter queue for poison messages.

**Rationale**: This is a migration, not a redesign. The existing pattern works in production and must remain backward-compatible with the Alkemio server. Message acknowledgment happens after successful processing (at-least-once delivery).

**Alternatives considered**:
- Higher prefetch for throughput → Rejected per spec: sequential processing (FR-022), concurrency can be added later per-plugin.
- Different serialization (msgpack, protobuf) → Rejected: wire contract compatibility is non-negotiable (FR-002, FR-012).

### 2.4 Shared Ingest Pipeline

**Decision**: Extract the common 70-75% of the ingest pipeline into `core/domain/ingest_pipeline.py`. Plugin-specific logic (crawling, GraphQL fetching) remains in the plugin. The shared pipeline handles: chunking → summarization → embedding → batch storage.

**Rationale**: Both ingest-space and ingest-website use identical RecursiveCharacterTextSplitter, LangGraph summarize-then-refine, embedding generation, and ChromaDB batch upsert. Only the document source differs.

**Alternatives considered**:
- Duplicate pipeline in each plugin → Rejected: violates DRY, creates the same duplication problem we're solving.
- Pipeline as a port interface → Rejected: it's domain logic that composes ports, not a port itself. It belongs in `core/domain/`.

**Configuration differences to resolve**:
| Parameter | ingest-space (TS) | ingest-website (Py) | Unified Default |
|---|---|---|---|
| Chunk size | 1,000 (env) | 2,000 (env) | Configurable via `CHUNK_SIZE` (default 2000) |
| Chunk overlap | 100 (fixed) | 20% of chunk size | Configurable via `CHUNK_OVERLAP` (default 400) |
| Batch size | 20 (fixed) | 20 (env) | Configurable via `BATCH_SIZE` (default 20) |
| Summary threshold | N/A | Length-based (10,000 chars) | Configurable via `SUMMARY_LENGTH` (default 10000) |

### 2.5 TypeScript-to-Python Port Strategy (ingest-space)

**Decision**: Full Python rewrite using equivalent libraries. Replace `@alkemio/client-lib` with `httpx` GraphQL client + Kratos auth. Replace npm file parsers with Python equivalents.

**Rationale**: 6 of 7 services are Python. A single ecosystem eliminates the npm/Poetry split, enables shared ingest pipeline, and uses LangChain Python's more stable document loaders.

**Alternatives considered**:
- Keep TypeScript service as-is → Rejected: perpetuates the language split, prevents code sharing with ingest-website, and requires separate CI/CD.
- Use Python subprocess to call Node.js → Rejected: adds runtime dependency, complexity, and defeats the purpose of consolidation.

**Port mapping**:
| TypeScript | Python Equivalent |
|---|---|
| `pdf-parse` | `pypdf` (PyPDF2) |
| `mammoth` | `python-docx` |
| `xlsx` | `openpyxl` |
| `officeparser` (ODT) | `python-docx` (limited) or `odfpy` |
| `@alkemio/client-lib` | `httpx` + manual GraphQL queries |
| `amqplib` | `aio-pika` (shared transport adapter) |
| `@langchain/text-splitters` | `langchain-text-splitters` |
| `Azure OpenAI (embeddings)` | Scaleway/OpenAI via `EmbeddingsPort` |

### 2.6 LLM Provider Abstraction

**Decision**: Two-tier port design. `LLMPort` for standard chat completion (used by expert, generic, guidance, ingest plugins). Separate `OpenAIAssistantAdapter` for the openai-assistant plugin (uses Assistants API directly).

**Rationale**: The Assistants API (threads, runs, file attachments, polling) is fundamentally different from chat completion (`invoke(messages) → str`). Forcing it behind `LLMPort` would create a leaky abstraction. Per constitution P3, the OpenAI Assistant exception is documented and justified.

**Alternatives considered**:
- Single `LLMPort` for everything → Rejected: thread_id, assistant_id, polling semantics don't map to `invoke(messages)`.
- `AssistantPort` protocol → Considered viable but YAGNI: only one plugin uses it. The adapter can implement the OpenAI-specific logic directly.

### 2.7 Health Endpoints

**Decision**: Lightweight HTTP server (built-in `aiohttp` or simple `asyncio` HTTP handler) exposing `/healthz` (liveness) and `/readyz` (readiness).

**Rationale**: Kubernetes requires HTTP health probes. The health server runs alongside the RabbitMQ consumer in the same async event loop. Liveness checks process aliveness; readiness checks RabbitMQ connection + plugin startup completion.

**Alternatives considered**:
- FastAPI → Rejected: heavyweight for two endpoints. Adds dependency for no benefit.
- TCP socket probe → Rejected: Kubernetes HTTP probes provide richer semantics (status codes, response bodies for debugging).
- RabbitMQ heartbeat as health signal → Rejected: doesn't distinguish between "process alive but not ready" and "fully operational".

### 2.8 Logging Strategy

**Decision**: JSON structured logging with `structlog` or Python's built-in `logging` with a JSON formatter. Standard fields: `timestamp`, `level`, `plugin_type`, `message`, `correlation_id`.

**Rationale**: Per FR-020, consistent JSON logging across core and plugins enables log aggregation in Kubernetes (ELK/Loki). The `correlation_id` is derived from the RabbitMQ message ID or correlation header for request tracing.

**Alternatives considered**:
- Plain text logging → Rejected: not parseable by log aggregation tools.
- `structlog` → Preferred for its context binding (`structlog.get_logger().bind(plugin_type="expert")`) but adds a dependency. Either approach satisfies the requirement.

### 2.9 Configuration Management

**Decision**: `pydantic-settings` (`BaseSettings`) for all configuration. Environment variables are the sole configuration source, matching existing Kubernetes secrets/configmaps deployment model.

**Rationale**: Already a dependency in `pyproject.toml`. Provides validation, type coercion, and env var binding. Each plugin can define a settings subclass extending the base config with plugin-specific fields.

**Alternatives considered**:
- YAML/TOML config files → Rejected: adds file management in containers. Env vars are the established pattern.
- `python-dotenv` only → Rejected: no validation, no type coercion. Already using `load-dotenv` for local dev, but `pydantic-settings` provides the structured config layer on top.

## 3. Testing Strategy

### 3.1 Test Categories

**Decision**: Three test layers aligned with the architecture.

| Layer | What | How | Target Coverage |
|---|---|---|---|
| **Core unit tests** | Ports (protocol compliance), Registry, Router, Container, Events (serialization) | pytest with mock ports | ≥80% |
| **Domain tests** | Ingest pipeline, PromptGraph, Summarize graph | pytest with mock LLM/embeddings/knowledge ports | ≥80% |
| **Plugin tests** | Handler logic, edge cases, error paths | pytest with mock ports injected via constructor | Per-plugin, ported from existing where available |

### 3.2 Ported Tests

| Source Repo | Test LOC | Port Strategy |
|---|---|---|
| engine-expert | ~200 LOC (4 modules) | Port directly, adapt to plugin constructor injection |
| engine-openai-assistant | 411 LOC (2.16:1 ratio) | Port directly, mock OpenAI client |
| ingest-website | 862 LOC (90% enforced) | Port directly, most valuable test suite |
| engine-generic | None | Write new: history condensation, direct LLM call |
| engine-guidance | None | Write new: multi-collection retrieval, score filtering |
| ingest-space | None | Write new: GraphQL client, space traversal, file parsing |

### 3.3 Non-Deterministic LLM Tests (Constitution P4)

**Decision**: LLM response tests verify behavioral properties, not exact text.

**Rationale**: Per Constitution P4, non-deterministic tests validate stochastic LLM behavior. Assertions check: response is non-empty, contains expected semantic markers, respects token limits, handles error conditions.

## 4. Deployment Architecture

### 4.1 Docker Image Strategy

**Decision**: Single multi-stage Dockerfile. `PLUGIN_TYPE` env var selects the active plugin at container runtime (not build time).

**Rationale**: All plugins share the same Python dependencies (already in `pyproject.toml`). Runtime selection via env var means one image serves all 6 plugin types without conditional builds.

**Build stages**:
1. **Builder**: Poetry install dependencies
2. **Runtime**: Slim Python image with installed packages + source code

### 4.2 CI/CD Matrix Strategy

**Decision**: ~5 GitHub Actions workflow files with matrix strategy replacing 28 separate files.

**Rationale**: Per PRD §3.6, matrix strategy parameterizes the plugin type across build, test, and deploy jobs. Changes to deployment logic require updating one workflow, not 28.

**Planned workflows**:
1. `ci.yml` — Lint, type check, test (matrix per plugin)
2. `build.yml` — Docker build + push (single image)
3. `deploy-dev.yml` — Deploy to dev (matrix per plugin)
4. `deploy-test.yml` — Deploy to test/sandbox (matrix per plugin)
5. `release.yml` — Tag + DockerHub release

## 5. Risk Mitigations

| Risk | Mitigation |
|---|---|
| RabbitMQ wire contract breaks | Exact field names, camelCase aliases, queue names preserved. Contract tests validate serialization. |
| TypeScript→Python ingest-space regressions | Comprehensive tests for GraphQL client, space traversal, file parsing. Parallel deployment during cutover. |
| Base engine has no tests | Write core tests FIRST before porting plugins. ≥80% coverage target. |
| Guidance hardcoded collection names | Make collection names configurable via plugin config (env vars or input). |
| OpenAI Assistant different interaction model | Separate adapter, not forced behind LLMPort. Documented exception in constitution. |
| Plugin dependency loading all adapters | Lazy adapter import — only resolve adapters declared by the active plugin. |
