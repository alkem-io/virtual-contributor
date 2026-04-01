# Tasks: Unified Microkernel Virtual Contributor Engine

**Input**: Design documents from `/specs/001-microkernel-engine-impl/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included — success criteria SC-003 (>=80% core coverage) and SC-004 (ported test suites) explicitly require tests.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- Single project: `core/`, `plugins/`, `tests/` at repository root (per plan.md)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Complete directory scaffolding and project configuration.

- [X] T001 Create missing directory structure and __init__.py files (tests/core/, tests/core/domain/, tests/plugins/, docs/adr/) per plan.md layout
- [X] T002 [P] Create .env.example with all environment variables from data-model.md section 2.6 (BaseConfig + plugin-specific configs)
- [X] T003 [P] Add missing dependencies to pyproject.toml (pypdf, python-docx, openpyxl for ingest-space file parsers per research.md section 2.5)
- [X] T074 [P] Configure pre-commit hooks (.pre-commit-config.yaml) running ruff check, pyright type check, and pytest to mirror CI workflow (T063) per Constitution P4

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core system components that MUST be complete before ANY user story can be implemented.

**CRITICAL**: No user story work can begin until this phase is complete.

### Event Models (Wire Contract)

- [X] T004 [P] Create base event model with populate_by_name=True, use_enum_values=True, and by_alias=True default serialization in core/events/base.py
- [X] T005 [P] Create Input event hierarchy (Input, HistoryItem, MessageSenderRole, InvocationOperation, ExternalConfig, ExternalMetadata, ResultHandler, ResultHandlerAction, RoomDetails) with camelCase aliases per data-model.md section 1 in core/events/input.py
- [X] T006 [P] Create Response and Source models with camelCase aliases per data-model.md sections 1.10-1.11 in core/events/response.py
- [X] T007 [P] Create IngestWebsite, IngestWebsiteResult, and IngestionResult enum per data-model.md sections 1.12-1.13 in core/events/ingest_website.py
- [X] T008 [P] Create IngestBodyOfKnowledge, IngestBodyOfKnowledgeResult, and ErrorDetail per data-model.md sections 1.14-1.15 in core/events/ingest_space.py
- [X] T009 Update core/events/__init__.py with public re-exports of all event models and enums

### Port Interfaces (Protocols)

- [X] T010 [P] Create runtime-checkable LLMPort protocol (async invoke, async stream) in core/ports/llm.py
- [X] T011 [P] Create runtime-checkable EmbeddingsPort protocol (async embed) in core/ports/embeddings.py
- [X] T012 [P] Create runtime-checkable KnowledgeStorePort protocol (async query, async ingest, async delete_collection) with QueryResult dataclass in core/ports/knowledge_store.py
- [X] T013 [P] Create runtime-checkable TransportPort protocol (async consume, async publish, async close) in core/ports/transport.py
- [X] T014 Update core/ports/__init__.py with public re-exports of all port protocols

### Core Infrastructure

- [X] T015 Create BaseConfig and plugin-specific config classes (IngestSpaceConfig, IngestWebsiteConfig, OpenAIAssistantConfig, ExpertConfig) using Pydantic Settings with env var binding per data-model.md section 2.6 in core/config.py
- [X] T016 Create IoC Container with register(port, adapter), resolve(port), and resolve_for_plugin(plugin) per data-model.md section 2.5 in core/container.py
- [X] T017 Create Plugin Registry with import-based discovery (_plugins dict, register, get, list_plugins) per research.md section 2.1 in core/registry.py
- [X] T018 Create JSON structured logging module with timestamp, level, plugin_type, message, correlation_id fields per FR-020 in core/logging.py

### Foundational Tests

- [X] T019 Create shared test fixtures (mock LLMPort, mock EmbeddingsPort, mock KnowledgeStorePort, mock TransportPort, sample Input/Response/IngestWebsite event factories) in tests/conftest.py
- [X] T020 [P] Contract tests for all event models (camelCase alias serialization, envelope format, round-trip model_dump/model_validate, enum values) per contracts/rabbitmq-events.md section Contract Tests in tests/core/test_events.py
- [X] T021 [P] Unit tests for IoC Container (register adapter, resolve port, resolve_for_plugin with declared deps only, missing port error) in tests/core/test_container.py
- [X] T022 [P] Unit tests for Plugin Registry (register class, get by name, list_plugins, import-based discovery, unknown plugin error) in tests/core/test_registry.py

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Core Message Processing (Priority: P1) MVP

**Goal**: The engine receives RabbitMQ messages, routes them to the correct plugin handler, and publishes a response in the exact wire format the Alkemio platform expects.

**Independent Test**: Send a well-formed RabbitMQ message with engine type "generic" and verify the system routes it to GenericPlugin and returns a valid Response wrapped in `{"response": {...}, "original": {...}}`.

### Implementation for User Story 1

- [X] T023 [US1] Create Content-Based Router (route by eventType discriminator or PLUGIN_TYPE, parse Input from body["input"], parse IngestWebsite/IngestBodyOfKnowledge from body root) per data-model.md section 2.4 in core/router.py
- [X] T024 [US1] Create RabbitMQ transport adapter (aio-pika, prefetch=1, manual ACK, dead-letter queue, DIRECT exchange, per-plugin queue/result-queue/routing-key from config) per contracts/rabbitmq-events.md in core/adapters/rabbitmq.py
- [X] T025 [P] [US1] Create lightweight async HTTP health server (/healthz liveness returns 200, /readyz readiness checks RabbitMQ + plugin startup) per contracts/health-endpoints.md in core/health.py
- [X] T026 [P] [US1] Create Mistral LLM adapter wrapping langchain-mistralai ChatMistral behind LLMPort with retry (exponential backoff, max 3 attempts per FR-018) in core/adapters/mistral.py
- [X] T027 [P] [US1] Create OpenAI LLM adapter wrapping langchain-openai ChatOpenAI behind LLMPort with retry (exponential backoff, max 3 attempts per FR-018) in core/adapters/openai_llm.py
- [X] T028 [US1] Create generic plugin prompt templates (condenser_system_prompt for history condensation) in plugins/generic/prompts.py
- [X] T029 [US1] Create GenericPlugin handler (per-request LLM selection via input.engine + external_config.api_key, history condensation, system messages from input.prompt, direct invoke) per research.md section 1.2 in plugins/generic/plugin.py
- [X] T030 [US1] Create application bootstrap and entry point (load config, discover plugin via registry, wire adapters via container, call plugin.startup, start transport consume, start health server, SIGTERM/SIGINT shutdown) in main.py

### Tests for User Story 1

- [X] T031 [P] [US1] Unit tests for Content-Based Router (Input routing via body["input"], IngestWebsite routing via eventType, IngestBodyOfKnowledge routing, unknown type error response, malformed message handling) in tests/core/test_router.py
- [X] T032 [P] [US1] Unit tests for GenericPlugin (direct LLM invoke, history condensation with condenser prompt, per-request engine selection, system message handling, error response on LLM failure) in tests/plugins/test_generic.py

**Checkpoint**: Core message flow works end-to-end with GenericPlugin — send message, route, handle, respond

---

## Phase 4: User Story 2 — Engine Plugin Functionality (Priority: P2)

**Goal**: Expert, guidance, and openai-assistant plugins reproduce the exact behavior of their current standalone repositories, maintaining backward compatibility with the Alkemio platform.

**Independent Test**: Send each plugin the same messages its current standalone counterpart receives and verify identical response structure and content quality.

### Implementation for User Story 2

- [X] T033 [P] [US2] Create PromptGraph domain logic (Node, Edge, dynamic state model via json_schema_to_pydantic, LangGraph StateGraph compilation, special node injection, streaming execution) per data-model.md section 3.3 in core/domain/prompt_graph.py
- [X] T034 [P] [US2] Create ChromaDB knowledge store adapter (chromadb-client, query with n_results, batch ingest with ids/metadatas, delete_collection, combine_query_results helper) behind KnowledgeStorePort with retry (exponential backoff, max 3 attempts per FR-018) in core/adapters/chromadb.py
- [X] T035 [P] [US2] Create OpenAI Assistant adapter (AsyncOpenAI client factory, thread create/retrieve, message add, file list/attach with file_search, run create/poll with configurable timeout) in core/adapters/openai_assistant.py
- [X] T036 [US2] Create expert plugin prompt templates (combined_expert_prompt with {vc_name}/{knowledge}/{question}, evaluation_prompt, input_checker_prompt) per research.md section 1.2 in plugins/expert/prompts.py
- [X] T037 [US2] Create ExpertPlugin handler (compile PromptGraph from input.prompt_graph, inject retrieve special node querying {bodyOfKnowledgeId}-knowledge collection, stream graph, assemble Response with sources and language fields) in plugins/expert/plugin.py
- [X] T038 [P] [US2] Create guidance plugin prompt templates (multi-stage RAG: condense, retrieve, generate prompts) in plugins/guidance/prompts.py
- [X] T039 [US2] Create GuidancePlugin handler (history condensation, query 3 ChromaDB collections, filter by relevance score, parse JSON response for source scores) per research.md section 1.2 in plugins/guidance/plugin.py
- [X] T040 [P] [US2] Create OpenAI Assistant utils (strip citation annotations from TextContentBlock, thread ID management helpers) in plugins/openai_assistant/utils.py
- [X] T041 [US2] Create OpenAIAssistantPlugin handler (per-request AsyncOpenAI client via external_config.api_key, thread create or resume via external_metadata.thread_id, file attachment, run polling with RUN_POLL_TIMEOUT_SECONDS, return Response with thread_id) in plugins/openai_assistant/plugin.py

### Tests for User Story 2

- [X] T042 [P] [US2] Unit tests for PromptGraph (node compilation with ChatPromptTemplate + PydanticOutputParser, edge traversal, dynamic state model building, special node injection, streaming output) in tests/core/domain/test_prompt_graph.py
- [X] T043 [P] [US2] Unit tests for ExpertPlugin (graph execution with mock LLM, knowledge retrieval with mock KnowledgeStore, response assembly with sources, language fields) in tests/plugins/test_expert.py
- [X] T044 [P] [US2] Unit tests for GuidancePlugin (multi-collection query, relevance score filtering, JSON response parsing, history condensation, empty collection handling) in tests/plugins/test_guidance.py
- [X] T045 [P] [US2] Unit tests for OpenAIAssistantPlugin (thread creation, thread resumption, file attachment, run polling, timeout error, citation stripping) in tests/plugins/test_openai_assistant.py

**Checkpoint**: All four engine plugins functional — expert, generic (from US1), guidance, openai-assistant

---

## Phase 5: User Story 3 — Content Ingestion (Priority: P3)

**Goal**: Website crawling and Alkemio space ingestion produce indexed knowledge in the vector store, enabling RAG-based responses from expert and guidance plugins.

**Independent Test**: Trigger website ingestion for a known URL and verify documents appear in the vector store with correct metadata (documentId, source, type, title, chunkIndex).

### Implementation for User Story 3

- [X] T046 [P] [US3] Create Scaleway embeddings adapter (httpx client, batch embed via Scaleway API) behind EmbeddingsPort with retry (exponential backoff, max 3 attempts per FR-018) in core/adapters/scaleway_embeddings.py
- [X] T047 [P] [US3] Create OpenAI embeddings adapter (openai SDK, batch embed) behind EmbeddingsPort with retry (exponential backoff, max 3 attempts per FR-018) in core/adapters/openai_embeddings.py
- [X] T048 [US3] Create summarization graph (LangGraph summarize-then-refine, SummarizeState with chunks/index/summary, document_graph with progressive length budgeting 40%-100%, bok_graph for body-of-knowledge) per data-model.md section 3.5 in core/domain/summarize_graph.py
- [X] T049 [US3] Create shared ingest pipeline with Document, DocumentMetadata, DocumentType, Chunk, ChunkMetadata, IngestResult domain models and pipeline (RecursiveCharacterTextSplitter chunking, optional summarization via summarize_graph, embedding via EmbeddingsPort, batch storage via KnowledgeStorePort) per data-model.md section 3.1 and research.md section 2.4 in core/domain/ingest_pipeline.py
- [X] T050 [P] [US3] Create recursive web crawler (domain boundary enforcement, URL normalization, file-link filtering for 65+ extensions, configurable page limit via PROCESS_PAGES_LIMIT, robots.txt skip) per research.md section 1.3 in plugins/ingest_website/crawler.py
- [X] T051 [P] [US3] Create HTML content parser (BeautifulSoup extraction from semantic tags: p, section, article, h1, title) per research.md section 1.3 in plugins/ingest_website/html_parser.py
- [X] T052 [US3] Create IngestWebsitePlugin handler (crawl URL, extract HTML, create Documents, run ingest pipeline, return IngestWebsiteResult, handle collection replacement on re-ingestion) in plugins/ingest_website/plugin.py
- [X] T053 [P] [US3] Create GraphQL client with Kratos authentication (httpx, Kratos login flow for auth_admin_email/password, authenticated GraphQL query helper for private API) with retry (exponential backoff, max 3 attempts per FR-018) for transient errors per research.md section 1.3 in plugins/ingest_space/graphql_client.py
- [X] T054 [P] [US3] Create file parsers (PDF text extraction via pypdf, DOCX via python-docx, XLSX via openpyxl) per research.md section 2.5 in plugins/ingest_space/file_parsers.py
- [X] T055 [US3] Create recursive space tree reader (3-level hierarchy traversal, callout processing for posts/whiteboards/link-collections, file download and parsing) in plugins/ingest_space/space_reader.py
- [X] T056 [US3] Create IngestSpacePlugin handler (fetch space tree via GraphQL, parse files, run ingest pipeline with chunk_size=9000/overlap=500, return IngestBodyOfKnowledgeResult, reject concurrent same-source requests per FR-021) in plugins/ingest_space/plugin.py

### Tests for User Story 3

- [X] T057 [P] [US3] Unit tests for summarize graph (refine pattern iteration, progressive length budgeting, empty chunk list, single chunk passthrough) in tests/core/domain/test_summarize_graph.py
- [X] T058 [P] [US3] Unit tests for ingest pipeline (chunking with configurable size/overlap, embedding batching, batch storage, metadata propagation, IngestResult assembly) in tests/core/domain/test_ingest_pipeline.py
- [X] T059 [P] [US3] Unit tests for IngestWebsitePlugin (crawl with mock httpx, domain boundary enforcement, page limit, HTML extraction, collection replacement, unsupported file skip) in tests/plugins/test_ingest_website.py
- [X] T060 [P] [US3] Unit tests for IngestSpacePlugin (GraphQL query with mock client, space tree traversal, file parsing for PDF/DOCX/XLSX, duplicate rejection, error handling for unsupported formats) in tests/plugins/test_ingest_space.py

**Checkpoint**: Both ingest plugins functional — website crawling and space ingestion produce indexed knowledge

---

## Phase 6: User Story 4 — Single-Image Deployment (Priority: P4)

**Goal**: One Docker image serves all 6 plugin types via PLUGIN_TYPE env var. Matrix-based CI reduces 28 workflow files to ~5.

**Independent Test**: Build the image once, launch containers with different PLUGIN_TYPE values, verify each correctly loads its plugin and responds to health checks.

### Implementation for User Story 4

- [X] T061 [US4] Create multi-stage Dockerfile (builder: Poetry install deps, runtime: slim Python 3.12 + source, PLUGIN_TYPE selected at runtime not build time) per research.md section 4.1 in Dockerfile
- [X] T062 [US4] Create docker-compose.yaml (one service per plugin type using same image with different PLUGIN_TYPE, plus RabbitMQ and ChromaDB infrastructure services) in docker-compose.yaml
- [X] T063 [US4] Create CI workflow (ruff lint, pyright type check, pytest with --cov-fail-under=80 per SC-003, matrix strategy per plugin type) in .github/workflows/ci.yml
- [X] T064 [P] [US4] Create Docker build and push workflow (build single image, tag, push to registry) in .github/workflows/build.yml
- [X] T065 [P] [US4] Create dev deployment workflow (matrix per plugin type, Kubernetes deploy) in .github/workflows/deploy-dev.yml

**Checkpoint**: Single image builds and deploys all 6 plugin types via CI matrix

---

## Phase 7: User Story 5 — Plugin Extensibility (Priority: P5)

**Goal**: Validate the microkernel architecture's key promise: a new plugin can be added with zero core code modifications.

**Independent Test**: Create a minimal "echo" plugin, verify registry discovers it and router dispatches to it without any modifications to core/, main.py, or configuration beyond PLUGIN_TYPE.

### Implementation for User Story 5

- [X] T066 [US5] Create minimal echo test plugin (implements PluginContract: name="echo", event_type=Input, handle returns input message as response) in tests/plugins/echo_plugin/plugin.py
- [X] T067 [US5] Integration test verifying echo plugin auto-discovery by registry and routing by router without any core code changes in tests/core/test_extensibility.py

**Checkpoint**: Microkernel extensibility promise validated — new plugin with zero core changes (SC-006)

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Architecture documentation (P8 constitution requirement), validation, and cleanup.

- [X] T068 [P] Write ADR 0001: Microkernel + Hexagonal architecture decision (context, decision, consequences) in docs/adr/0001-microkernel-hexagonal-architecture.md
- [X] T069 [P] Write ADR 0002: TypeScript-to-Python port decision for ingest-space in docs/adr/0002-typescript-to-python-port.md
- [X] T070 [P] Write ADR 0003: Plugin contract design (Protocol-based, constructor injection, lifecycle methods) in docs/adr/0003-plugin-contract-design.md
- [X] T071 [P] Write ADR 0004: Sequential processing model (prefetch=1, horizontal scaling via replicas) in docs/adr/0004-sequential-processing-model.md
- [X] T072 Run quickstart.md validation (poetry install, docker-compose up, health checks, pytest suite)
- [X] T073 Final linting pass (ruff check + pyright) and code cleanup across core/ and plugins/

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — creates the core message flow
- **US2 (Phase 4)**: Depends on Foundational — plugin handlers testable in isolation with mock ports; full integration requires US1 transport
- **US3 (Phase 5)**: Depends on Foundational — ingest plugins testable in isolation with mock ports; full integration requires US1 transport
- **US4 (Phase 6)**: Depends on US1 + US2 + US3 — all plugins must exist for single image and CI matrix
- **US5 (Phase 7)**: Depends on US1 — needs working registry and router
- **Polish (Phase 8)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Foundational — no dependencies on other stories
- **US2 (P2)**: Can start after Foundational — plugin handlers testable in isolation with mock ports. Full integration depends on US1 transport layer.
- **US3 (P3)**: Can start after Foundational — ingest plugins testable in isolation with mock ports. Full integration depends on US1 transport layer.
- **US4 (P4)**: Depends on US1 + US2 + US3 — all plugins must be functional for Docker image and CI matrix
- **US5 (P5)**: Can start after US1 — needs working registry and router for echo plugin test

### Within Each User Story

- Domain logic and adapters before plugins that use them
- Prompt templates before plugin handlers
- Plugin implementation before plugin tests
- Core components before integration validation

### Parallel Opportunities

- All event models (T004-T008) can run in parallel — independent files
- All port protocols (T010-T013) can run in parallel — independent files
- Foundation tests (T020-T022) can run in parallel — after T019 conftest
- US1: Health server (T025), Mistral adapter (T026), OpenAI adapter (T027) in parallel — independent files
- US2: PromptGraph (T033), ChromaDB adapter (T034), OAI adapter (T035) in parallel — independent files
- US2: Expert prompts (T036), Guidance prompts (T038), OAI utils (T040) in parallel — independent files
- US2: All plugin tests (T042-T045) in parallel — after their respective plugins
- US3: Embeddings adapters (T046-T047) in parallel — independent files
- US3: Crawler (T050), HTML parser (T051) in parallel — independent files
- US3: GraphQL client (T053), file parsers (T054) in parallel — independent files
- US3: All ingest tests (T057-T060) in parallel — after their respective implementations
- US4: Build workflow (T064), deploy workflow (T065) in parallel — independent files
- All ADRs (T068-T071) in parallel — independent documents

---

## Parallel Example: User Story 2

```bash
# Launch all independent domain/adapters together:
Task: "Create PromptGraph domain logic in core/domain/prompt_graph.py"
Task: "Create ChromaDB knowledge store adapter in core/adapters/chromadb.py"
Task: "Create OpenAI Assistant adapter in core/adapters/openai_assistant.py"

# Launch all prompt templates together:
Task: "Create expert plugin prompt templates in plugins/expert/prompts.py"
Task: "Create guidance plugin prompt templates in plugins/guidance/prompts.py"
Task: "Create OpenAI Assistant utils in plugins/openai_assistant/utils.py"

# Launch all plugin tests together (after plugin implementation):
Task: "Unit tests for PromptGraph in tests/core/domain/test_prompt_graph.py"
Task: "Unit tests for ExpertPlugin in tests/plugins/test_expert.py"
Task: "Unit tests for GuidancePlugin in tests/plugins/test_guidance.py"
Task: "Unit tests for OpenAIAssistantPlugin in tests/plugins/test_openai_assistant.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (Core Message Processing + GenericPlugin)
4. **STOP and VALIDATE**: Send a RabbitMQ message, verify routing and response format
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational -> Foundation ready
2. Add US1 -> Test core message flow -> Deploy/Demo (MVP!)
3. Add US2 -> Test all four engine plugins -> Deploy/Demo
4. Add US3 -> Test ingestion pipelines -> Deploy/Demo
5. Add US4 -> Single image, CI matrix -> Deploy/Demo
6. Add US5 -> Extensibility validated -> Final release
7. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: US1 (core message flow + generic plugin)
   - Developer B: US2 plugins (expert, guidance, openai-assistant — testable with mock ports)
   - Developer C: US3 ingest (pipeline + ingest plugins — testable with mock ports)
3. US4 and US5 follow after integration validation

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All wire contract field names must use camelCase aliases for backward compatibility (verified in contracts/rabbitmq-events.md)
- GenericPlugin is in US1 (not US2) because it is the simplest way to validate the core message flow end-to-end
- The "human" role value (not "user") in MessageSenderRole is a critical backward compatibility requirement
