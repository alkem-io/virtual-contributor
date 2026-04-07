# Alkemio Virtual Contributor

Unified microkernel engine with pluggable handlers for AI-powered virtual contributors. Consolidates 7 formerly standalone services into a single Python 3.12 codebase using a **microkernel + hexagonal (ports and adapters)** architecture.

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Repository Structure](#repository-structure)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Plugins](#plugins)
- [Ingest Pipeline](#ingest-pipeline)
- [Docker Deployment](#docker-deployment)
- [RAG Evaluation Framework](#rag-evaluation-framework)
- [Testing](#testing)
- [Linting and Type Checking](#linting-and-type-checking)
- [Adding a New Plugin](#adding-a-new-plugin)
- [Architecture Decision Records](#architecture-decision-records)
- [License](#license)

## Features

- **Multi-provider LLM support** — Mistral, OpenAI, and Anthropic via a unified LangChain adapter with per-plugin overrides
- **Configurable summarization** — Optional separate LLM for ingest pipeline summarization
- **RAG with score filtering** — Single-collection and multi-collection retrieval with configurable score thresholds and context budgets
- **PromptGraph engine** — JSON-defined LangGraph workflows with dynamic Pydantic schema generation
- **Content-hash deduplication** — SHA-256 fingerprinting with change detection and orphan cleanup during ingest
- **Ingest pipelines** — Website crawling and Alkemio space tree ingestion with chunking, summarization, and embedding
- **RAG evaluation** — RAGAS-based quality measurement with faithfulness, relevancy, precision, and recall metrics
- **Plugin architecture** — Duck-typed protocol contract; add new plugins with zero core code changes
- **IoC container** — Automatic dependency injection via `__init__` type hint introspection
- **Sequential processing** — `prefetch=1` per instance; horizontal scaling via Kubernetes replicas
- **Health monitoring** — HTTP health server with liveness (`/healthz`) and readiness (`/readyz`) endpoints

## Architecture

The system follows two complementary patterns:

**Microkernel** — `core/` is the core system that provides infrastructure (routing, configuration, dependency injection, transport). `plugins/` are independently deployable components that implement the `PluginContract` protocol.

**Hexagonal (Ports and Adapters)** — External dependencies (LLMs, vector database, message broker, embeddings) are accessed through `@runtime_checkable` Protocol interfaces in `core/ports/`. Concrete adapters in `core/adapters/` can be swapped without changing plugin code.

### Ports (Interfaces)

| Port | Methods | Purpose |
|------|---------|---------|
| `LLMPort` | `invoke(messages)`, `stream(messages)` | Chat model invocation and streaming |
| `EmbeddingsPort` | `embed(texts)` | Batch text embedding |
| `KnowledgeStorePort` | `query()`, `ingest()`, `get()`, `delete()`, `delete_collection()` | Vector database operations |
| `TransportPort` | `connect()`, `consume()`, `publish()`, `close()` | Message broker communication |

### Adapters (Implementations)

| Adapter | Implements | Technology |
|---------|-----------|------------|
| `LangChainLLMAdapter` | `LLMPort` | Any LangChain `BaseChatModel` (Mistral, OpenAI, Anthropic) |
| `ChromaDBAdapter` | `KnowledgeStorePort` | ChromaDB (HTTP client mode) |
| `RabbitMQAdapter` | `TransportPort` | RabbitMQ via aio-pika |
| `OpenAICompatibleEmbeddingsAdapter` | `EmbeddingsPort` | OpenAI-compatible API (Scaleway, vLLM, etc.) |
| `OpenAIAssistantAdapter` | N/A | OpenAI Assistants API (threads, runs, files) |

### Message Flow

```
RabbitMQ message
    |
    v
Router.parse_event(body)          # Dispatches to correct Pydantic event model
    |
    v
Plugin.handle(event)              # Plugin-specific logic (RAG, LLM call, ingest, etc.)
    |
    v
Router.build_response_envelope()  # Wraps response for wire format
    |
    v
RabbitMQ publish (result queue)
```

### Startup Sequence

```
main.py
  |- Load BaseConfig (env vars + .env)
  |- Setup JSON structured logging
  |- Resolve plugin-specific LLM overrides ({PLUGIN_NAME}_LLM_*)
  |- PluginRegistry.discover(PLUGIN_TYPE)
  |- Container.register() adapters:
  |    |- LLMPort        <- create_llm_adapter(config)
  |    |- EmbeddingsPort <- OpenAICompatibleEmbeddingsAdapter
  |    |- KnowledgeStorePort <- ChromaDBAdapter
  |    '- OpenAIAssistantAdapter
  |- Container.resolve_for_plugin(PluginClass)  # Auto-inject via type hints
  |- Plugin.startup()
  |- RabbitMQAdapter.connect() + consume(queue, handler)
  |- HealthServer.start(:8080)
  '- await SIGTERM/SIGINT -> graceful shutdown
```

## Repository Structure

```
virtual-contributor/
├── core/                              # Core system
│   ├── ports/                         # Technology-agnostic interfaces
│   │   ├── llm.py                     # LLMPort — chat model invocation
│   │   ├── embeddings.py              # EmbeddingsPort — text embedding
│   │   ├── knowledge_store.py         # KnowledgeStorePort — vector DB
│   │   └── transport.py               # TransportPort — message bus
│   ├── adapters/                      # Concrete implementations
│   │   ├── langchain_llm.py           # Unified LLM (any LangChain provider)
│   │   ├── openai_assistant.py        # OpenAI Assistants API
│   │   ├── chromadb.py                # ChromaDB vector store
│   │   ├── rabbitmq.py                # RabbitMQ transport (aio-pika)
│   │   ├── openai_compatible_embeddings.py  # OpenAI-compatible embeddings
│   │   └── openai_embeddings.py       # OpenAI embeddings
│   ├── domain/                        # Shared domain logic
│   │   ├── prompt_graph.py            # LangGraph workflow engine
│   │   ├── ingest_pipeline.py         # Document, Chunk, IngestResult models
│   │   ├── summarize_graph.py         # Summarize-then-refine pattern
│   │   └── pipeline/                  # Ingest pipeline engine
│   │       ├── engine.py              # Ordered step executor
│   │       └── steps.py              # Chunk, Hash, Detect, Summarize, Embed, Store, Cleanup
│   ├── events/                        # Pydantic wire-format models
│   │   ├── input.py                   # Input, HistoryItem, ExternalConfig
│   │   ├── response.py               # Response, Source
│   │   ├── ingest_website.py          # IngestWebsite
│   │   └── ingest_space.py            # IngestBodyOfKnowledge
│   ├── config.py                      # Pydantic Settings (env var binding)
│   ├── container.py                   # IoC container (port -> adapter)
│   ├── registry.py                    # Plugin registry (import-based discovery)
│   ├── router.py                      # Content-based message router
│   ├── provider_factory.py            # LLM provider switching (Mistral/OpenAI/Anthropic)
│   ├── health.py                      # HTTP health server (/healthz, /readyz)
│   └── logging.py                     # JSON structured logging
│
├── plugins/                           # Plugin implementations
│   ├── expert/                        # PromptGraph + knowledge retrieval RAG
│   ├── generic/                       # Direct LLM with history condensation
│   ├── guidance/                      # Multi-collection RAG with score filtering
│   ├── openai_assistant/              # OpenAI Assistants API (threads/runs/files)
│   ├── ingest_website/                # Web crawler + HTML parser + ingest
│   └── ingest_space/                  # Alkemio space tree reader + file parsers
│
├── evaluation/                        # RAG evaluation framework (RAGAS)
│   ├── cli.py                         # Click CLI (run, compare, generate, list)
│   ├── dataset.py                     # Golden test set I/O (JSONL)
│   ├── metrics.py                     # RAGAS metric configuration
│   ├── pipeline_invoker.py            # Direct plugin invocation for eval
│   ├── runner.py                      # Evaluation orchestration + scoring
│   ├── generator.py                   # Synthetic test case generation
│   └── report.py                      # Result reporting
│
├── tests/                             # Test suite (mirrors source layout)
│   ├── conftest.py                    # Mock ports, event factories
│   ├── core/                          # Core unit + contract tests
│   └── plugins/                       # Plugin unit tests
│
├── docs/adr/                          # Architecture Decision Records
├── main.py                            # Single entry point
├── Dockerfile                         # Multi-stage build (PLUGIN_TYPE at runtime)
├── docker-compose.yaml                # All services from one image
├── pyproject.toml                     # Poetry config + test/coverage settings
└── .github/workflows/                 # CI/CD (lint, test, build, deploy)
```

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) (dependency management)
- Docker + Docker Compose (for local infrastructure or full deployment)

## Getting Started

### Install dependencies

```bash
poetry install
```

### Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys and service endpoints
```

### Run a single plugin

```bash
PLUGIN_TYPE=generic poetry run python main.py
```

The process loads config from environment variables, discovers the plugin specified by `PLUGIN_TYPE`, wires adapter dependencies via the IoC container, and starts consuming from the configured RabbitMQ queue.

### Run all plugins with Docker Compose

```bash
# Build the image
docker build -t alkemio/virtual-contributor .

# Start all plugins + RabbitMQ + ChromaDB
docker-compose up
```

Each plugin runs in its own container from the same image, differentiated only by the `PLUGIN_TYPE` environment variable.

### Health checks

```bash
curl http://localhost:8080/healthz   # Liveness probe
curl http://localhost:8080/readyz    # Readiness probe (RabbitMQ + plugin status)
```

## Configuration

All configuration is via environment variables (or `.env` file). See `.env.example` for a complete reference.

### Core

| Variable | Default | Description |
|----------|---------|-------------|
| `PLUGIN_TYPE` | `generic` | Plugin to run (`expert`, `generic`, `guidance`, `openai-assistant`, `ingest-website`, `ingest-space`) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `HEALTH_PORT` | `8080` | Health server port |

### RabbitMQ

| Variable | Default | Description |
|----------|---------|-------------|
| `RABBITMQ_HOST` | `localhost` | Broker hostname |
| `RABBITMQ_PORT` | `5672` | Broker port |
| `RABBITMQ_USER` | `alkemio-admin` | Username |
| `RABBITMQ_PASSWORD` | `alkemio!` | Password |
| `RABBITMQ_QUEUE` | `virtual-contributor-engine-{plugin}` | Input queue name |
| `RABBITMQ_EVENT_BUS_EXCHANGE` | `event-bus` | Exchange for publishing results |
| `RABBITMQ_RESULT_ROUTING_KEY` | `invoke-engine-result` | Routing key for results |

### Vector Database (ChromaDB)

| Variable | Default | Description |
|----------|---------|-------------|
| `VECTOR_DB_HOST` | `localhost` | ChromaDB hostname |
| `VECTOR_DB_PORT` | `8765` | ChromaDB port |
| `VECTOR_DB_CREDENTIALS` | _(empty)_ | Optional auth token |

### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `mistral` | Provider: `mistral`, `openai`, or `anthropic` |
| `LLM_API_KEY` | _(required)_ | API key for the chosen provider |
| `LLM_MODEL` | Provider default | Model name (e.g. `mistral-large-latest`, `gpt-4o`, `claude-sonnet-4-6`) |
| `LLM_BASE_URL` | _(empty)_ | Custom endpoint for local/self-hosted models |
| `LLM_TEMPERATURE` | _(provider default)_ | Sampling temperature (0.0-2.0) |
| `LLM_MAX_TOKENS` | _(provider default)_ | Maximum output tokens |
| `LLM_TOP_P` | _(provider default)_ | Nucleus sampling (0.0-1.0) |
| `LLM_TIMEOUT` | `120` | Request timeout in seconds |

### Per-Plugin LLM Overrides

Any LLM setting can be overridden per plugin by prefixing with the plugin name in uppercase:

```bash
EXPERT_LLM_PROVIDER=anthropic
EXPERT_LLM_MODEL=claude-sonnet-4-6
EXPERT_LLM_API_KEY=sk-ant-...
```

### Summarization LLM

A separate LLM can be configured for ingest pipeline summarization. All three fields are required to enable:

| Variable | Description |
|----------|-------------|
| `SUMMARIZE_LLM_PROVIDER` | Provider for summarization |
| `SUMMARIZE_LLM_MODEL` | Model name |
| `SUMMARIZE_LLM_API_KEY` | API key |
| `SUMMARIZE_LLM_TEMPERATURE` | Sampling temperature (optional) |
| `SUMMARIZE_LLM_TIMEOUT` | Request timeout (optional) |

### Retrieval Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPERT_N_RESULTS` | `5` | Number of chunks to retrieve (expert plugin) |
| `EXPERT_MIN_SCORE` | `0.3` | Minimum relevance score (expert plugin) |
| `GUIDANCE_N_RESULTS` | `5` | Number of chunks per collection (guidance plugin) |
| `GUIDANCE_MIN_SCORE` | `0.3` | Minimum relevance score (guidance plugin) |
| `MAX_CONTEXT_CHARS` | `20000` | Context budget — lowest-scoring chunks dropped first |

### Embeddings

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDINGS_API_KEY` | _(required for ingest)_ | API key for embedding service |
| `EMBEDDINGS_ENDPOINT` | `https://api.scaleway.ai/v1` | Embedding API endpoint |
| `EMBEDDINGS_MODEL_NAME` | `qwen3-embedding-8b` | Embedding model |

### Ingest Pipeline

| Variable | Default | Description |
|----------|---------|-------------|
| `CHUNK_SIZE` | `2000` | Characters per chunk |
| `CHUNK_OVERLAP` | `400` | Overlap between chunks |
| `BATCH_SIZE` | `20` | Embedding batch size |
| `SUMMARY_LENGTH` | `10000` | Max summary length |
| `SUMMARY_CHUNK_THRESHOLD` | `4` | Minimum chunks to trigger summarization |
| `PROCESS_PAGES_LIMIT` | `20` | Max pages to crawl (ingest-website) |

### Backward Compatibility

Legacy Mistral-specific variables (`MISTRAL_API_KEY`, `MISTRAL_SMALL_MODEL_NAME`) are still supported and used as fallbacks when the corresponding `LLM_*` variables are not set.

## Plugins

### Expert (`PLUGIN_TYPE=expert`)

**Queue**: `virtual-contributor-engine-expert`

PromptGraph-based plugin with single-collection RAG. If the incoming event includes a `prompt_graph` definition, it compiles a LangGraph workflow from JSON — nodes have prompt templates, input variables, and optional output schemas. A special "retrieve" node queries the knowledge store. Falls back to simple RAG if no graph is defined. Results are filtered by score threshold and capped by context budget.

### Generic (`PLUGIN_TYPE=generic`)

**Queue**: `virtual-contributor-engine-generic`

Direct LLM invocation with optional chat history condensation. When conversation history is present, it first condenses prior exchanges into a standalone question via the LLM, then builds a message array from system prompts and the condensed question. Returns raw LLM output with no sources.

### Guidance (`PLUGIN_TYPE=guidance`)

**Queue**: `virtual-contributor-engine-guidance`

Multi-collection RAG that queries three Alkemio knowledge bases in parallel (`alkem.io-knowledge`, `welcome.alkem.io-knowledge`, `www.alkemio.org-knowledge`). Merges results, deduplicates by source URL (keeping the highest score per page), filters by threshold, and enforces context budget. Context chunks are prefixed with `[source:N]` citations. Parses the LLM's JSON response to extract the answer.

### OpenAI Assistant (`PLUGIN_TYPE=openai-assistant`)

**Queue**: `virtual-contributor-engine-openai-assistant`

Wraps the OpenAI Assistants API with thread and run management. Requires per-request `external_config` with `api_key` and `assistant_id`. Creates or resumes threads (via `thread_id` in `external_metadata`), adds messages, polls runs to completion, and returns the answer with thread ID for conversation continuity.

### Ingest Website (`PLUGIN_TYPE=ingest-website`)

**Queue**: `virtual-contributor-ingest-website`

Web crawler that fetches pages from a base URL (configurable page limit), extracts text and titles from HTML via BeautifulSoup, then runs the full ingest pipeline. The collection is named `{domain}-knowledge`.

### Ingest Space (`PLUGIN_TYPE=ingest-space`)

**Queue**: `virtual-contributor-ingest-body-of-knowledge`

Fetches the Alkemio space tree via GraphQL, parses attached files (PDF, DOCX, XLSX), and runs the ingest pipeline with larger chunk sizes (9000 characters). The collection is named `{body_of_knowledge_id}-{purpose}`.

## Ingest Pipeline

Both ingest plugins share a common pipeline engine (`core/domain/pipeline/`) that executes an ordered sequence of steps:

```
Documents
    |
    v
ChunkStep                  # Split documents via RecursiveCharacterTextSplitter
    |
    v
ContentHashStep             # SHA-256 fingerprint: content + title + source + type + document_id
    |
    v
ChangeDetectionStep         # Query store for existing chunks, mark unchanged, identify orphans
    |
    v
DocumentSummaryStep         # Per-document summaries (>= chunk_threshold chunks, refine pattern)
    |
    v
BodyOfKnowledgeSummaryStep  # Single overview summary for entire knowledge base
    |
    v
EmbedStep                   # Batch embed all chunks via EmbeddingsPort
    |
    v
StoreStep                   # Persist to ChromaDB (content hash as ID)
    |
    v
OrphanCleanupStep           # Delete orphaned/removed document chunks
```

**Content-hash deduplication**: Each chunk gets a SHA-256 fingerprint computed from its content, title, source, type, and document ID. During change detection, existing chunks in the store are compared by hash — unchanged chunks skip re-embedding, saving compute. Orphaned chunks (from deleted or modified documents) are cleaned up after the store step succeeds.

Each step reports metrics (duration, items in/out, error count) and failures are caught per-step so the pipeline can continue with remaining steps.

## Docker Deployment

### Image

The project uses a multi-stage Docker build:

- **Builder stage**: Installs Poetry, resolves dependencies with `--no-root`
- **Runtime stage**: Copies only `site-packages`, `core/`, `plugins/`, and `main.py`
- Exposes port `8080` for the health server
- Default `PLUGIN_TYPE=generic`, overridable at runtime

```bash
docker build -t alkemio/virtual-contributor .
```

### Docker Compose

The `docker-compose.yaml` runs the full stack from a single image:

**Infrastructure:**
- RabbitMQ (AMQP :5672, management UI :15672)
- ChromaDB (:8765)

**Engine plugins** (each a separate container):
- expert, generic, guidance, openai-assistant

**Ingest plugins** (each a separate container):
- ingest-website, ingest-space

Each service sets its own `PLUGIN_TYPE` and queue configuration. All services share the same RabbitMQ and ChromaDB instances.

```bash
docker-compose up        # Start everything
docker-compose up expert # Start just the expert plugin + dependencies
```

## RAG Evaluation Framework

The `evaluation/` module provides systematic RAG quality measurement using [RAGAS](https://docs.ragas.io/).

### Metrics

| Metric | What it Measures |
|--------|-----------------|
| **Faithfulness** | Is the answer grounded in the retrieved context? |
| **Answer Relevancy** | Does the answer address the question? |
| **Context Precision** | Are the retrieved chunks relevant to the question? |
| **Context Recall** | Are all necessary chunks retrieved? |

### Usage

```bash
# Run evaluation against the guidance plugin
poetry run python -m evaluation.cli run --plugin guidance --test-set evaluation/data/test_set.jsonl

# Compare two evaluation runs
poetry run python -m evaluation.cli compare --baseline <run-id-1> --current <run-id-2>

# Generate synthetic test cases from a ChromaDB collection
poetry run python -m evaluation.cli generate --collection alkem.io-knowledge --output evaluation/data/test_set.jsonl

# List previous evaluation runs
poetry run python -m evaluation.cli list
```

### How it Works

1. **Golden test set**: JSONL file with `question`, `expected_answer`, and `relevant_documents` fields
2. **Pipeline invoker**: Instantiates the plugin directly (bypassing RabbitMQ) with a `TracingKnowledgeStore` that captures retrieved contexts
3. **Scorer**: Wraps RAGAS metrics, uses the pipeline's own LLM as judge via `LangchainLLMWrapper`
4. **Runner**: Executes the test suite, computes per-metric aggregates, persists results to `evaluations/{id}.json`

## Testing

Tests use `asyncio_mode = "auto"` — async test functions run automatically without `@pytest.mark.asyncio`.

```bash
# Run all tests
poetry run pytest

# With coverage report
poetry run pytest --cov=core --cov=plugins --cov-report=term-missing

# Single file
poetry run pytest tests/plugins/test_expert.py

# Single test
poetry run pytest tests/plugins/test_expert.py::test_handle
```

### Test Infrastructure

- **Mock ports** (`tests/conftest.py`): `MockLLMPort`, `MockEmbeddingsPort`, `MockKnowledgeStorePort` — in-memory implementations with call tracking
- **Event factories**: `make_input(...)`, `make_ingest_website(...)` — build test events with sensible defaults
- **Coverage**: Minimum 80% enforced in CI; adapters, config, health, logging, and main.py are excluded from coverage

### Testing Pattern

```python
async def test_expert_handle():
    llm = MockLLMPort(responses=["The answer is 42."])
    store = MockKnowledgeStorePort(results=[...])
    plugin = ExpertPlugin(llm=llm, knowledge_store=store)

    response = await plugin.handle(make_input(message="What is the answer?"))

    assert "42" in response.result
    assert len(store.query_calls) == 1
```

## Linting and Type Checking

```bash
# Lint with Ruff
poetry run ruff check core/ plugins/ tests/

# Type check with Pyright
poetry run pyright core/ plugins/
```

Both checks are enforced in CI.

## Adding a New Plugin

1. Create `plugins/{name}/plugin.py` with a class implementing the `PluginContract`:

```python
from core.events.input import Input
from core.events.response import Response
from core.ports.llm import LLMPort


class MyPlugin:
    name = "my-plugin"
    event_type = Input

    def __init__(self, llm: LLMPort):
        self._llm = llm

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def handle(self, event: Input) -> Response:
        result = await self._llm.invoke([{"role": "user", "content": event.message}])
        return Response(result=result)
```

2. Port dependencies declared as `__init__` type hints are resolved automatically by the IoC container
3. Add tests in `tests/plugins/test_{name}.py`
4. Run with `PLUGIN_TYPE={name} poetry run python main.py`

No core code changes required. See `docs/adr/0003-plugin-contract-design.md` for the full contract specification.

## Architecture Decision Records

Detailed design rationale is documented in `docs/adr/`:

| ADR | Decision |
|-----|----------|
| 0001 | Microkernel + hexagonal architecture consolidating 7 repositories |
| 0002 | TypeScript-to-Python port for ingest-space plugin |
| 0003 | Duck-typed plugin contract via Python Protocol |
| 0004 | Sequential message processing with horizontal scaling |
| 0005 | Unified LangChain adapter with provider factory |
| 0006a | RAGAS as RAG evaluation framework |
| 0006b | Content-hash deduplication and KnowledgeStorePort extension |

## CI/CD

| Workflow | Trigger | What it Does |
|----------|---------|--------------|
| `ci.yml` | Push/PR | Ruff lint, Pyright type check, pytest with 80% coverage minimum |
| `build.yml` | Push to `develop`/`main`, tags | Docker build and push with branch/semver/SHA tags |
| `deploy-dev.yml` | After successful build on `develop` | Deploys all 6 plugins to alkemio-dev Kubernetes namespace |

## License

[EUPL-1.2](https://joinup.ec.europa.eu/collection/eupl/eupl-text-eupl-12) (European Union Public Licence)
