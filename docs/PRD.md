# PRD: Alkemio Virtual Contributor — Unified Microkernel Engine

**Status:** Draft
**Date:** 2026-03-30
**Authors:** Valentin Yanakiev, Claude (AI-assisted analysis)

---

## 1. Executive Summary

This document captures the findings from a comprehensive analysis of Alkemio's 8 active virtual-contributor repositories and proposes their consolidation into a single unified repository (`virtual-contributor`) using a **Microkernel Architecture** with **Hexagonal (Ports and Adapters)** internal structure.

The current architecture spreads ~460 lines of unique engine logic across 8 separate repositories, each carrying ~2,500 lines of duplicated boilerplate (Dockerfiles, CI workflows, manifests, config, packaging). This consolidation targets **7 public repositories** (libra-flow is private and will follow later).

---

## 2. Problem Statement

### 2.1 Repository Proliferation

| Repository | Language | Unique LOC | Total LOC | Base Engine Ver | Status |
|---|---|---|---|---|---|
| virtual-contributor-engine | Python 3.12 | 1,292 | 1,292 | N/A (is the base) | Active, Public |
| virtual-contributor-engine-guidance | Python 3.11 | ~50 | 307 | **v0.7.0** (stale) | Active, Public |
| virtual-contributor-engine-generic | Python 3.11 | ~30 | 174 | **v0.7.0** (stale) | Active, Public |
| virtual-contributor-engine-expert | Python 3.12 | ~60 | 504 | v0.8.0 | Active, Public |
| virtual-contributor-engine-openai-assistant | Python 3.12 | ~70 | 190 | v0.8.0 | Active, Public |
| virtual-contributor-engine-libra-flow | Python 3.12 | ~250 | 910 | v0.8.0 | Active, **Private** |
| virtual-contributor-ingest-space | TypeScript | ~3,000 | ~21,470 (19.8K gen) | N/A | Active, Public |
| virtual-contributor-ingest-website | Python 3.12 | ~300 | 506 | v0.8.0 | Active, Public |
| virtual-contributor-engine-community-manager | Python | — | — | — | **Archived** |

### 2.2 Key Problems

#### A. Boilerplate Duplication (~60-70% per repo)

Every engine repo duplicates:
- **main.py**: Identical bootstrap pattern — instantiate `AlkemioVirtualContributorEngine`, register handler, `asyncio.run(engine.start())`
- **config.py**: Near-identical env var loading (LOG_LEVEL, HISTORY_LENGTH, LOCAL_PATH)
- **ai_adapter.py**: Same try/except wrapper with fallback error Response
- **Dockerfile**: Same multi-stage Poetry build (builder → slim/distroless runtime)
- **4 GitHub Actions workflows** per repo: dev/test/sandbox deploy + DockerHub release — **28 nearly identical workflow files** across all repos
- **Kubernetes manifests**: Same deployment template with env from shared secrets/configmaps
- **.flake8, docker-compose.yaml, .env.default**: Identical across repos

#### B. Version Drift

- Guidance and Generic are pinned to **Python 3.11** and base engine **v0.7.0**, while the base engine requires **3.12** and is at v0.8.0
- Upgrading the base engine requires bumping git tags in 6 separate repos, testing each, deploying each

#### C. Inconsistent Testing

| Repo | Tests | CI Pipeline |
|---|---|---|
| engine (base) | **None** | **No CI** |
| engine-guidance | **None** | No CI test job |
| engine-generic | **None** | No CI test job |
| engine-expert | Good (4 modules) | Yes |
| engine-openai-assistant | Excellent (2.16:1 ratio) | Yes |
| ingest-space | **None** | No CI test job |
| ingest-website | Excellent (90% enforced) | Yes |

The base engine — the foundation all others depend on — has **zero tests and zero CI**.

#### D. Language Split

`ingest-space` is the only TypeScript service. Everything else is Python. This creates:
- Two dependency management systems (npm vs Poetry)
- Two different embedding implementations (Azure OpenAI in TS vs Scaleway in Python)
- Different LLM providers for summarization
- Different ChromaDB client versions
- No code sharing between ingestion services

#### E. LLM/Embedding Provider Fragmentation

| Repo | LLM Provider | Embedding Provider |
|---|---|---|
| engine-guidance | Mistral Medium (via base) | Azure OpenAI Ada |
| engine-generic | OpenAI GPT-4o (direct) | None (no RAG) |
| engine-expert | Mistral Small (via base) | Scaleway Qwen3 |
| engine-openai-assistant | OpenAI Assistants API | OpenAI (managed) |
| ingest-space | Azure Mistral (summarize) | Azure OpenAI (embed) |
| ingest-website | Mistral Small (via base) | Scaleway Qwen3 |

Four LLM providers, three embedding providers — each requiring separate API keys, billing, monitoring.

#### F. CI/CD Workflow Explosion

28 GitHub Actions workflow files across 8 repos. Changes to deployment strategy require updating all 28 files.

---

## 3. Proposed Solution

### 3.1 Architecture: Microkernel + Hexagonal (Ports and Adapters)

The solution applies three established architectural patterns:

1. **Microkernel Architecture** (Richards/Ford, *Fundamentals of Software Architecture*) — the primary structural pattern. A minimal **Core System** loads **Plugin Components** via a **Plugin Registry** that conform to a **Plugin Contract**.

2. **Hexagonal Architecture / Ports and Adapters** (Cockburn, 2005) — governs how plugins access external systems. Infrastructure dependencies are accessed through **Ports** (technology-agnostic interfaces defined by the core) with concrete **Adapters** (technology-specific implementations). Plugins never import concrete adapters directly.

3. **Content-Based Router** (Hohpe/Woolf, *Enterprise Integration Patterns*) — governs message dispatch. The core examines message content (engine type, event type) to route to the correct plugin.

#### Dependency Injection

Per Fowler (*Inversion of Control Containers and the Dependency Injection Pattern*, 2004): dependencies are injected into plugins via **Constructor Injection**, not resolved via Service Locator. The **IoC Container** registers adapter implementations and resolves port interfaces at startup.

### 3.2 Directory Structure

```
virtual-contributor/
├── core/
│   ├── ports/                    # Driven (Secondary) Port interfaces
│   │   ├── llm.py                # LLM port — Protocol for chat model invocation
│   │   ├── embeddings.py         # Embeddings port — Protocol for text embedding
│   │   ├── knowledge_store.py    # Knowledge store port — Protocol for vector DB queries
│   │   └── transport.py          # Transport port — Protocol for message consume/publish
│   │
│   ├── adapters/                 # Driven (Secondary) Adapter implementations
│   │   ├── mistral.py            # Mistral LLM adapter
│   │   ├── openai_llm.py         # OpenAI ChatCompletion adapter
│   │   ├── openai_assistant.py   # OpenAI Assistants API adapter
│   │   ├── chromadb.py           # ChromaDB knowledge store adapter
│   │   ├── rabbitmq.py           # RabbitMQ transport adapter
│   │   ├── scaleway_embeddings.py
│   │   └── openai_embeddings.py
│   │
│   ├── domain/                   # Internal shared logic (not ports, not adapters)
│   │   ├── ingest_pipeline.py    # chunk → summarize → embed → store
│   │   ├── summarize_graph.py    # LangGraph summarize-then-refine pattern
│   │   └── prompt_graph.py       # PromptGraph execution engine (from base engine)
│   │
│   ├── container.py              # IoC Container — registers adapters, resolves ports
│   ├── registry.py               # Plugin Registry (Microkernel)
│   ├── router.py                 # Content-Based Router (EIP)
│   ├── events/                   # Message schemas
│   │   ├── input.py              # Input, HistoryItem, RoomDetails, etc.
│   │   ├── response.py           # Response with sources
│   │   ├── ingest_website.py     # IngestWebsite event
│   │   ├── ingest_space.py       # IngestBodyOfKnowledge event
│   │   └── base.py               # Base event model
│   └── config.py                 # Base configuration (Pydantic Settings)
│
├── plugins/                      # Plugin Components (Microkernel)
│   ├── expert/
│   │   ├── plugin.py             # PluginContract implementation (~60 LOC)
│   │   └── prompts.py            # Expert-specific prompts
│   ├── generic/
│   │   ├── plugin.py             # (~30 LOC)
│   │   └── prompts.py
│   ├── guidance/
│   │   ├── plugin.py             # (~50 LOC)
│   │   └── prompts.py
│   ├── openai_assistant/
│   │   ├── plugin.py             # (~70 LOC)
│   │   └── utils.py
│   ├── ingest_space/
│   │   ├── plugin.py             # RabbitMQ handler
│   │   ├── graphql_client.py     # Alkemio GraphQL queries
│   │   ├── space_reader.py       # Recursive space tree traversal
│   │   └── file_parsers.py       # PDF, DOCX, XLSX loaders
│   └── ingest_website/
│       ├── plugin.py             # RabbitMQ handler
│       ├── crawler.py            # Web crawling + URL filtering
│       └── html_parser.py        # BeautifulSoup extraction
│
├── main.py                       # Single entry point — loads plugins, starts core
├── Dockerfile                    # Single multi-stage image, PLUGIN_TYPE selects at runtime
├── docker-compose.yaml           # All services from one image
├── pyproject.toml
├── .github/workflows/            # ~5 workflows with matrix strategy
├── manifests/                    # K8s deployment manifests
├── tests/
│   ├── core/                     # Core system tests
│   ├── plugins/                  # Per-plugin tests
│   └── conftest.py
└── docs/
    └── PRD.md                    # This document
```

### 3.3 Plugin Contract

```python
from typing import Protocol, runtime_checkable
from core.ports.llm import LLMPort
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.events.input import Input
from core.events.response import Response


@runtime_checkable
class PluginContract(Protocol):
    """Microkernel: Plugin Contract.

    Each plugin declares its name, the event type it handles,
    and a handle() method that receives injected port dependencies.
    """
    name: str
    event_type: type  # Input | IngestWebsite | IngestBodyOfKnowledge

    async def handle(self, event, **ports) -> Response: ...
```

### 3.4 Port Interfaces

```python
# core/ports/llm.py
from typing import Protocol

class LLMPort(Protocol):
    """Driven port: LLM invocation.
    Adapters: MistralAdapter, OpenAIAdapter, etc.
    """
    async def invoke(self, messages: list[dict]) -> str: ...
    async def stream(self, messages: list[dict]): ...


# core/ports/knowledge_store.py
class KnowledgeStorePort(Protocol):
    """Driven port: vector knowledge store.
    Adapters: ChromaDBAdapter, etc.
    """
    def query(self, collection: str, query: str, n_results: int = 10) -> list[dict]: ...
    def ingest(self, collection: str, documents: list, metadatas: list) -> None: ...
    def delete_collection(self, collection: str) -> None: ...


# core/ports/embeddings.py
class EmbeddingsPort(Protocol):
    """Driven port: text embedding.
    Adapters: ScalewayAdapter, OpenAIEmbeddingsAdapter, etc.
    """
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

### 3.5 Deployment Model

One Docker image, multiple containers differentiated by `PLUGIN_TYPE` env var:

```yaml
# docker-compose.yaml
services:
  engine-expert:
    image: alkemio/virtual-contributor:latest
    environment:
      PLUGIN_TYPE: expert
      RABBITMQ_QUEUE: virtual-contributor-engine-expert

  engine-generic:
    image: alkemio/virtual-contributor:latest
    environment:
      PLUGIN_TYPE: generic
      RABBITMQ_QUEUE: virtual-contributor-engine-generic

  ingest-website:
    image: alkemio/virtual-contributor:latest
    environment:
      PLUGIN_TYPE: ingest-website
      RABBITMQ_QUEUE: virtual-contributor-ingest-website
```

### 3.6 CI/CD: Matrix Workflows

Replace 28 workflow files with ~5 using GitHub Actions matrix strategy:

```yaml
# .github/workflows/deploy-k8s.yml
strategy:
  matrix:
    plugin: [expert, generic, guidance, openai-assistant, ingest-space, ingest-website]
    environment: [dev, test, sandbox]
```

---

## 4. Source Repository Analysis

### 4.1 virtual-contributor-engine (Base Library)

**Role:** Shared PyPI package providing the foundation for all VC engines.

**Public API (from `__init__.py`):**
- `AlkemioVirtualContributorEngine` — core engine entry point, RabbitMQ message loop
- `RabbitMQ` — message broker abstraction
- `PromptGraph` — graph-based prompt execution framework (LangGraph)
- Event models: `Input`, `Response`, `IngestWebsite`, `IngestWebsiteResult`, `HistoryItem`, `MessageSenderRole`
- Utilities: `setup_logger()`, `query_documents()`, `ingest_documents()`, `combine_query_results()`, `history_as_text()`, `history_as_conversation()`, `history_as_dict()`
- Model singletons: `chromadb_client`, `mistral_small`, `embeddings`

**Architecture:**
- `alkemio_vc_engine.py` (109 LOC) — main engine class, single handler registration, message routing
- `rabbitmq.py` (126 LOC) — async aio-pika wrapper, prefetch=1
- `config.py` (83 LOC) — Pydantic Settings for env vars
- `models.py` (27 LOC) — module-level singleton initialization of `mistral_small` and `embeddings`
- `prompt_graph/` (368 LOC) — LangGraph-based graph execution: `PromptGraph`, `Node`, `Edge`, `State`
- `chromadb_utils.py` (136 LOC) — `query_documents()`, `ingest_documents()`, `combine_query_results()`
- `events/` (197 LOC) — Pydantic models with camelCase aliases

**Key limitations for plugin architecture:**
1. `register_handler()` stores a single handler — no multi-handler routing
2. `models.py` creates singletons at module import — not injectable, fixed providers
3. `invoke_handler()` has hardcoded if/else on `eventType` — not extensible
4. `Input.engine` field exists but is never used for routing
5. ChromaDB is mandatory at import time — crashes if not configured even when unused

**Migration path:** This library's logic migrates into `core/` — broken apart into ports, adapters, domain, and events. The singleton models become adapter implementations behind port interfaces. The PromptGraph system moves to `core/domain/`. The RabbitMQ logic becomes a transport adapter.

### 4.2 virtual-contributor-engine-expert

**Unique logic (~60 LOC):**
- Compiles a PromptGraph from `input.prompt_graph` with a custom `retrieve` special node
- Streams execution through the compiled graph via `graph.stream(input_state, stream_mode="updates")`
- Maps document indices to relevance scores, reconstructs source metadata with formatted titles

**Ports needed:** LLM (Mistral Small), KnowledgeStore (ChromaDB query via `query_documents`)

**Data from Input:** `prompt_graph` (required), `body_of_knowledge_id`, `description`, `display_name`

**Tests:** 4 modules covering adapter, config, utils, main — good coverage.

### 4.3 virtual-contributor-engine-generic

**Unique logic (~30 LOC):**
- If chat history exists, uses a condenser LLM call to rephrase the current question with context
- Then makes a direct LLM call with optional system prompts from input
- No knowledge retrieval, no embeddings

**Ports needed:** LLM (configurable — accepts `engine` and `api_key` from `input.external_config`)

**Data from Input:** `engine`, `external_config.api_key`, `prompt` (system messages)

**Tests:** None.

### 4.4 virtual-contributor-engine-guidance

**Unique logic (~50 LOC):**
- Multi-stage: condense history → retrieve context from 3 ChromaDB collections → LLM response
- Parses JSON response from LLM to extract source scores
- Filters documents by relevance score

**Ports needed:** LLM (Mistral Medium), KnowledgeStore (ChromaDB — queries 3 hardcoded collections)

**Data from Input:** `language`, `message`

**Note:** Uses Python 3.11 and base engine v0.7.0 (stale). Has hardcoded collection names (`alkem.io-knowledge`, `welcome.alkem.io-knowledge`, `www.alkemio.org-knowledge`).

**Tests:** None.

### 4.5 virtual-contributor-engine-openai-assistant

**Unique logic (~70 LOC):**
- Creates or retrieves OpenAI threads based on `external_metadata.thread_id`
- Lists and attaches all files from the assistant's file storage
- Creates a run and polls for completion with configurable timeout (300s default)
- Strips OpenAI citation markers from response

**Ports needed:** OpenAI client (direct — not LLM port, uses Assistants API with threads/runs/files)

**Data from Input:** `external_config.assistant_id`, `external_config.api_key`, `external_metadata.thread_id`

**Note:** This plugin's LLM interaction is fundamentally different — it uses OpenAI's managed Assistants API, not a chat completion port. The OpenAI adapter for this plugin wraps the Assistants API, not the chat API.

**Tests:** Excellent — 411 LOC, 2.16:1 test-to-code ratio.

### 4.6 virtual-contributor-ingest-space (TypeScript — to be ported)

**Unique logic (~3,000 LOC custom + 19.8K generated GraphQL types):**
- Consumes `IngestBodyOfKnowledge` events from RabbitMQ (direct amqplib, not base engine)
- Authenticates via `@alkemio/client-lib` + Kratos
- Fetches space trees or knowledge bases via GraphQL (recursive 3-level hierarchy)
- Processes callouts: posts, whiteboards, link collections
- Downloads and parses files: PDF (pdf-parse), DOCX (mammoth), XLSX (xlsx), ODT (officeparser)
- Chunks with RecursiveCharacterTextSplitter (1000 chars, 100 overlap)
- Summarizes with LangGraph (Azure Mistral) — summarize-then-refine pattern
- Embeds with Azure OpenAI, upserts to ChromaDB in batches of 20
- Metadata: documentId, source, type, title, embeddingType, chunkIndex

**Port to Python rationale:**
- 6 of 7 other services are Python — single ecosystem is cheaper
- LangChain Python has more stable document loaders
- Can share the base engine's abstractions (currently can't — it's TypeScript)
- Core custom logic is ~3K LOC; the 19.8K generated GraphQL types can be replaced with a lightweight `graphql-request` client
- Python equivalents exist for all file parsers: `pypdf`, `python-docx`, `openpyxl`

**Shared with ingest-website (70-75% of pipeline):**
- Document chunking (RecursiveCharacterTextSplitter)
- Summarization (LangGraph summarize-then-refine — architecturally identical)
- Embedding + batching
- ChromaDB upsert + metadata schema

### 4.7 virtual-contributor-ingest-website

**Unique logic (~300 LOC):**
- Recursive web crawler with domain boundary enforcement
- URL normalization, file-link filtering (65+ extensions)
- HTML content extraction from semantic tags (p, section, article, h1, title)
- Progressive length budgeting for summarization (sophisticated: 40% → 100% scaling)
- Two-tier summarization: per-document + body-of-knowledge aggregate
- Configurable page limit (default 20)

**Ports needed:** LLM (Mistral Small), Embeddings (Scaleway Qwen3), KnowledgeStore (ChromaDB ingest)

**Tests:** Excellent — 862 LOC, 90% coverage enforced in CI.

---

## 5. Shared Infrastructure Analysis

### 5.1 Ingest Pipeline (core/domain)

Both ingest services implement the same pipeline with minor config differences:

| Concern | ingest-space (TS) | ingest-website (Py) | Unified |
|---|---|---|---|
| Splitter | RecursiveCharacterTextSplitter | RecursiveCharacterTextSplitter | Same |
| Chunk size | 1,000 (env) | 2,000 (env) | Configurable |
| Chunk overlap | 100 (fixed) | 20% of chunk size | Configurable |
| Summarization | LangGraph summarize-then-refine | LangGraph summarize-then-refine | Same architecture |
| Embedding | Azure OpenAI, batch=20 | Via engine lib | Configurable adapter |
| ChromaDB metadata | documentId, source, type, title, embeddingType, chunkIndex | Same fields | Identical schema |
| Collection naming | `{bokID}-{purpose}` | `{domain}-knowledge` | Plugin-determined |

The ingest pipeline in `core/domain/ingest_pipeline.py` will expose:

```python
async def ingest(
    documents: list[Document],
    collection_name: str,
    *,
    embeddings: EmbeddingsPort,
    knowledge_store: KnowledgeStorePort,
    llm: LLMPort,                    # for summarization
    chunk_size: int = 2000,
    chunk_overlap: int = 400,
    summary_threshold: int = 3,      # chunks before triggering summarization
    batch_size: int = 20,
) -> IngestResult: ...
```

### 5.2 PromptGraph (core/domain)

The existing PromptGraph system (368 LOC) from the base engine is used by the expert engine and potentially libra-flow. It provides graph-based LLM workflow execution using LangGraph StateGraph with:
- JSON-defined graph structure (nodes, edges, state schema)
- Special node injection (e.g., `retrieve` for knowledge lookup)
- Pydantic output model generation from JSON schema
- Streaming execution support

### 5.3 Message Transport

All services use RabbitMQ with consistent patterns:
- Prefetch=1 (sequential processing)
- Exclusive queues for request/response
- Event bus exchange for broadcasting results
- JSON serialization with camelCase field aliases

---

## 6. Migration Strategy

### Phase 1: Core System (Week 1)

1. Port base engine into `core/`:
   - `core/ports/` — define LLM, Embeddings, KnowledgeStore, Transport port interfaces
   - `core/adapters/` — implement Mistral, OpenAI, ChromaDB, RabbitMQ, Scaleway adapters
   - `core/events/` — port all Pydantic event models (Input, Response, IngestWebsite, etc.)
   - `core/domain/prompt_graph.py` — port PromptGraph system
   - `core/container.py` — IoC container for adapter registration/resolution
   - `core/registry.py` — plugin registry with content-based routing
2. Write comprehensive tests for core (the current base engine has none)

### Phase 2: Engine Plugins (Week 2)

Port engines in order of complexity:
1. `plugins/generic/` — simplest (~30 LOC), good first validation of plugin contract
2. `plugins/expert/` — well-tested, validates PromptGraph + knowledge store integration
3. `plugins/openai_assistant/` — validates alternative port usage (Assistants API)
4. `plugins/guidance/` — validates multi-collection knowledge queries

Bring along existing tests from expert and openai-assistant repos.

### Phase 3: Ingest Plugins (Week 3)

1. `core/domain/ingest_pipeline.py` — shared chunking, summarization, embedding pipeline
2. `plugins/ingest_website/` — port from Python repo (already Python, straightforward)
3. `plugins/ingest_space/` — port from TypeScript to Python:
   - Replace `@alkemio/client-lib` with lightweight Python GraphQL client
   - Replace npm document loaders with Python equivalents (pypdf, python-docx, openpyxl)
   - Replace amqplib with shared RabbitMQ transport adapter

### Phase 4: Infrastructure (Week 3-4)

1. Single Dockerfile with `PLUGIN_TYPE` build/runtime arg
2. Matrix-based GitHub Actions workflows
3. Kubernetes manifests (parameterized per plugin)
4. Docker Compose for local development (all plugins + dependencies)

### Phase 5: Validation and Cutover

1. Deploy consolidated services alongside existing ones
2. Validate message compatibility (same RabbitMQ contracts)
3. Run integration tests against Alkemio server
4. Cut over per-service, deprecate old repos
5. Archive old repositories

---

## 7. Scope: What's Included / Excluded

### Included (this PRD — 7 public repos)

- virtual-contributor-engine (base library → becomes core/)
- virtual-contributor-engine-expert → plugins/expert/
- virtual-contributor-engine-generic → plugins/generic/
- virtual-contributor-engine-guidance → plugins/guidance/
- virtual-contributor-engine-openai-assistant → plugins/openai_assistant/
- virtual-contributor-ingest-space → plugins/ingest_space/ (TypeScript → Python port)
- virtual-contributor-ingest-website → plugins/ingest_website/

### Excluded (follow-on work)

- **virtual-contributor-engine-libra-flow** — Private repo. Will be added as a plugin after the initial consolidation is validated. Its LangGraph-based workshop design state machine (~250 LOC) fits naturally as `plugins/libra_flow/`.
- **virtual-contributor-engine-community-manager** — Archived. No action needed.

---

## 8. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| RabbitMQ message contract breaks during migration | Services stop processing | Keep exact same queue names, event schemas, and serialization (camelCase aliases) |
| TypeScript → Python port introduces ingest-space regressions | Knowledge bases not indexed | Port with comprehensive tests; run both old and new in parallel during cutover |
| Plugin isolation — one plugin crash takes down all plugins in a process | Broader blast radius than separate containers | Deploy one plugin per container (same image, different PLUGIN_TYPE). Process isolation preserved. |
| Base engine has no tests — porting untested code | Bugs carried forward | Write core tests FIRST before porting plugins |
| Guidance engine's hardcoded collection names | Breaks if collections change | Make collection names configurable via plugin config |
| OpenAI Assistant's fundamentally different interaction model | Doesn't fit standard LLM port | Provide a separate `OpenAIAssistantAdapter` that wraps the Assistants API — not every plugin needs the same ports |

---

## 9. Success Criteria

1. **All 7 public repos' functionality reproduced** in the unified repo with passing tests
2. **Single Docker image** deployable as any plugin via PLUGIN_TYPE env var
3. **Message contract compatibility** — existing Alkemio server sends the same RabbitMQ messages, gets the same responses
4. **CI pipeline** — single set of matrix workflows replaces 28 separate workflow files
5. **Core test coverage** ≥ 80% (up from 0% in current base engine)
6. **Plugin test coverage** — at minimum, port existing tests from expert, openai-assistant, and ingest-website

---

## 10. Architectural Pattern References

| Pattern | Source | Application |
|---|---|---|
| **Microkernel Architecture** | Richards/Ford, *Fundamentals of Software Architecture* (O'Reilly, 2020) | Core System + Plugin Components + Plugin Registry + Plugin Contract |
| **Hexagonal Architecture (Ports and Adapters)** | Alistair Cockburn (2005) | Driven Ports (LLM, Embeddings, KnowledgeStore, Transport) + Driven Adapters (Mistral, OpenAI, ChromaDB, RabbitMQ) |
| **Content-Based Router** | Hohpe/Woolf, *Enterprise Integration Patterns* (2003) | Message dispatch by engine type / event type |
| **Dependency Injection** | Fowler, *Inversion of Control Containers and the Dependency Injection Pattern* (2004) | Constructor injection of port implementations into plugins |
| **Strategy Pattern** | Gamma et al., *Design Patterns* (GoF, 1994) | Each plugin is a ConcreteStrategy; the core is the Context |

---

## Appendix A: Environment Variables (Unified)

All env vars from all repos, deduplicated and organized:

### Core
```
PLUGIN_TYPE=expert                          # Which plugin to activate
LOG_LEVEL=INFO                              # DEBUG|INFO|WARNING|ERROR|CRITICAL
```

### RabbitMQ (Transport Adapter)
```
RABBITMQ_HOST=rabbitmq
RABBITMQ_USER=alkemio-admin
RABBITMQ_PASSWORD=alkemio!
RABBITMQ_PORT=5672
RABBITMQ_QUEUE=virtual-contributor-engine-expert    # Per-plugin
RABBITMQ_RESULT_QUEUE=virtual-contributor-invoke-engine-result
RABBITMQ_EVENT_BUS_EXCHANGE=event-bus
RABBITMQ_RESULT_ROUTING_KEY=invoke-engine-result
```

### LLM Adapters
```
# Mistral
MISTRAL_API_KEY=
MISTRAL_SMALL_MODEL_NAME=mistral-small-latest

# OpenAI (for plugins that need it)
# Passed per-request via input.external_config.api_key
```

### Embeddings Adapters
```
EMBEDDINGS_API_KEY=
EMBEDDINGS_ENDPOINT=https://api.scaleway.ai/v1
EMBEDDINGS_MODEL_NAME=qwen3-embedding-8b
```

### Knowledge Store (ChromaDB Adapter)
```
VECTOR_DB_HOST=localhost
VECTOR_DB_PORT=8000
VECTOR_DB_CREDENTIALS=root:toor
```

### Ingest Pipeline (Domain)
```
CHUNK_SIZE=2000
CHUNK_OVERLAP=400
BATCH_SIZE=20
SUMMARY_LENGTH=10000
```

### Ingest Space Plugin
```
API_ENDPOINT_PRIVATE_GRAPHQL=http://localhost:3000/api/private/non-interactive/graphql
AUTH_ORY_KRATOS_PUBLIC_BASE_URL=http://localhost:3000/ory/kratos/public
AUTH_ADMIN_EMAIL=master-admin@alkem.io
AUTH_ADMIN_PASSWORD=master-password
```

### Ingest Website Plugin
```
PROCESS_PAGES_LIMIT=20
```

### OpenAI Assistant Plugin
```
RUN_POLL_TIMEOUT_SECONDS=300
```

### Observability
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=virtual-contributor
```

### Legacy (to be removed after migration)
```
HISTORY_LENGTH=20                           # Moved to per-plugin config
AI_LOCAL_PATH=                              # Replaced by plugin-specific paths
AI_MODEL_TEMPERATURE=0.3                    # Moved to adapter config
```

---

## Appendix B: Current Repository URLs

| Repository | URL |
|---|---|
| virtual-contributor-engine | https://github.com/alkem-io/virtual-contributor-engine |
| virtual-contributor-engine-expert | https://github.com/alkem-io/virtual-contributor-engine-expert |
| virtual-contributor-engine-generic | https://github.com/alkem-io/virtual-contributor-engine-generic |
| virtual-contributor-engine-guidance | https://github.com/alkem-io/virtual-contributor-engine-guidance |
| virtual-contributor-engine-openai-assistant | https://github.com/alkem-io/virtual-contributor-engine-openai-assistant |
| virtual-contributor-engine-libra-flow | https://github.com/alkem-io/virtual-contributor-engine-libra-flow (private) |
| virtual-contributor-ingest-space | https://github.com/alkem-io/virtual-contributor-ingest-space |
| virtual-contributor-ingest-website | https://github.com/alkem-io/virtual-contributor-ingest-website |
| virtual-contributor-engine-community-manager | https://github.com/alkem-io/virtual-contributor-engine-community-manager (archived) |
