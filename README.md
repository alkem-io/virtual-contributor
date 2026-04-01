# Alkemio Virtual Contributor

Unified microkernel engine with pluggable handlers for AI-powered virtual contributors. Consolidates 7 standalone repositories into a single Python 3.12 codebase using a **microkernel + hexagonal (ports and adapters)** architecture.

## Repository Structure

```
virtual-contributor/
├── core/                          # Core system
│   ├── ports/                     # Technology-agnostic interfaces
│   │   ├── llm.py                 # LLMPort — chat model invocation
│   │   ├── embeddings.py          # EmbeddingsPort — text embedding
│   │   ├── knowledge_store.py     # KnowledgeStorePort — vector DB
│   │   └── transport.py           # TransportPort — message bus
│   ├── adapters/                  # Concrete implementations
│   │   ├── langchain_llm.py       # Unified LLM adapter (any LangChain provider)
│   │   ├── openai_assistant.py    # OpenAI Assistants API (threads/runs)
│   │   ├── chromadb.py            # ChromaDB vector store
│   │   ├── rabbitmq.py            # RabbitMQ transport (aio-pika)
│   │   ├── scaleway_embeddings.py # Scaleway embeddings (httpx)
│   │   └── openai_embeddings.py   # OpenAI embeddings
│   ├── domain/                    # Shared domain logic
│   │   ├── prompt_graph.py        # LangGraph-based workflow engine
│   │   ├── ingest_pipeline.py     # chunk → summarize → embed → store
│   │   └── summarize_graph.py     # Summarize-then-refine pattern
│   ├── events/                    # Pydantic wire-format models
│   │   ├── input.py               # Input, HistoryItem, ExternalConfig, ...
│   │   ├── response.py            # Response, Source
│   │   ├── ingest_website.py      # IngestWebsite, IngestWebsiteResult
│   │   └── ingest_space.py        # IngestBodyOfKnowledge, result
│   ├── config.py                  # Pydantic Settings (env var binding)
│   ├── container.py               # IoC Container (port → adapter)
│   ├── registry.py                # Plugin Registry (import-based discovery)
│   ├── router.py                  # Content-Based Router
│   ├── health.py                  # HTTP health server (/healthz, /readyz)
│   └── logging.py                 # JSON structured logging
│
├── plugins/                       # Plugin implementations
│   ├── expert/                    # PromptGraph + knowledge retrieval RAG
│   ├── generic/                   # Direct LLM with history condensation
│   ├── guidance/                  # Multi-collection RAG with score filtering
│   ├── openai_assistant/          # OpenAI Assistants API (threads/runs/files)
│   ├── ingest_website/            # Web crawler + HTML parser + ingest
│   └── ingest_space/              # Alkemio space tree reader + file parsers
│
├── tests/                         # Test suite (mirrors source layout)
│   ├── conftest.py                # Mock ports, event factories
│   ├── core/                      # Core unit + contract tests
│   └── plugins/                   # Plugin unit tests
│
├── docs/adr/                      # Architecture Decision Records
├── main.py                        # Single entry point
├── Dockerfile                     # Multi-stage (PLUGIN_TYPE at runtime)
├── docker-compose.yaml            # All services from one image
├── pyproject.toml                 # Poetry config + test/coverage settings
└── .github/workflows/             # CI/CD (lint, build, deploy)
```

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/)
- Docker + Docker Compose (for local services)

## Setup

```bash
# Install dependencies
poetry install

# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys
```

## Running

### Single plugin

```bash
# Set the plugin type and run
PLUGIN_TYPE=generic poetry run python main.py
```

The process loads config from environment variables, discovers the plugin specified by `PLUGIN_TYPE`, wires adapter dependencies, and starts consuming from the configured RabbitMQ queue.

### All plugins (Docker Compose)

```bash
# Build the image
docker build -t alkemio/virtual-contributor .

# Start all plugins + RabbitMQ + ChromaDB
docker-compose up
```

Each plugin runs in its own container from the same image, differentiated only by the `PLUGIN_TYPE` environment variable.

### Health checks

```bash
curl http://localhost:8080/healthz   # Liveness
curl http://localhost:8080/readyz    # Readiness (RabbitMQ + plugin status)
```

## Available Plugins

| Plugin | `PLUGIN_TYPE` | Input Queue | Description |
|--------|---------------|-------------|-------------|
| Expert | `expert` | `virtual-contributor-engine-expert` | PromptGraph + knowledge retrieval |
| Generic | `generic` | `virtual-contributor-engine-generic` | Direct LLM, per-request engine selection |
| Guidance | `guidance` | `virtual-contributor-engine-guidance` | Multi-collection RAG |
| OpenAI Assistant | `openai-assistant` | `virtual-contributor-engine-openai-assistant` | OpenAI Assistants API |
| Ingest Website | `ingest-website` | `virtual-contributor-ingest-website` | Web crawl + vectorize |
| Ingest Space | `ingest-space` | `virtual-contributor-ingest-body-of-knowledge` | Alkemio space tree + vectorize |

## Testing

```bash
# Run all tests
poetry run pytest

# With coverage
poetry run pytest --cov=core --cov=plugins --cov-report=term-missing

# Specific module
poetry run pytest tests/core/test_events.py
poetry run pytest tests/plugins/test_expert.py
```

## Linting

```bash
poetry run ruff check core/ plugins/ tests/
poetry run pyright core/ plugins/
```

## Adding a New Plugin

1. Create `plugins/{name}/plugin.py` with a class that has `name`, `event_type`, `startup()`, `shutdown()`, and `handle()`
2. Declare port dependencies as `__init__` parameters (resolved automatically by the IoC container)
3. Add tests in `tests/plugins/test_{name}.py`
4. Set `PLUGIN_TYPE={name}` and run

No core code changes required. See `docs/adr/0003-plugin-contract-design.md` for the full contract.

## Architecture

**Microkernel**: `core/` is the core system, `plugins/` are plugin components. Plugins implement `PluginContract` and are discovered at startup via the registry.

**Hexagonal**: External dependencies (LLM, embeddings, vector DB, transport) are accessed through port protocols in `core/ports/`. Concrete adapters in `core/adapters/` are swappable without changing plugin code.

**Message flow**:
```
RabbitMQ → Router.parse_event() → Plugin.handle(event) → Router.build_response_envelope() → RabbitMQ
```

See `docs/adr/` for detailed architecture decisions.

## License

EUPL-1.2
