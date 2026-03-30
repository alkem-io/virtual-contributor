# Quickstart: Unified Virtual Contributor Engine

**Feature**: 001-microkernel-engine-impl
**Date**: 2026-03-30

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/) (dependency management)
- Docker + Docker Compose (for local services)
- Access to LLM provider API keys (Mistral, OpenAI depending on plugin)

## Setup

### 1. Install Dependencies

```bash
cd virtual-contributor
poetry install
```

### 2. Start Infrastructure Services

RabbitMQ and ChromaDB are required for all plugins:

```bash
docker-compose up -d rabbitmq chromadb
```

### 3. Configure Environment

Copy the example env file and fill in your API keys:

```bash
cp .env.example .env
```

Minimum required env vars for any plugin:

```bash
# Core
PLUGIN_TYPE=generic              # Which plugin to run
LOG_LEVEL=INFO

# RabbitMQ
RABBITMQ_HOST=localhost
RABBITMQ_USER=alkemio-admin
RABBITMQ_PASSWORD=alkemio!
RABBITMQ_PORT=5672
RABBITMQ_QUEUE=virtual-contributor-engine-generic
RABBITMQ_RESULT_QUEUE=virtual-contributor-invoke-engine-result
RABBITMQ_EVENT_BUS_EXCHANGE=event-bus
RABBITMQ_RESULT_ROUTING_KEY=invoke-engine-result
```

Plugin-specific env vars — add only what your plugin needs:

```bash
# LLM (expert, generic, guidance, ingest plugins)
MISTRAL_API_KEY=your-key-here
MISTRAL_SMALL_MODEL_NAME=mistral-small-latest

# Embeddings (expert, guidance, ingest plugins)
EMBEDDINGS_API_KEY=your-key-here
EMBEDDINGS_ENDPOINT=https://api.scaleway.ai/v1
EMBEDDINGS_MODEL_NAME=qwen3-embedding-8b

# ChromaDB (expert, guidance, ingest plugins)
VECTOR_DB_HOST=localhost
VECTOR_DB_PORT=8765

# Ingest Space only
API_ENDPOINT_PRIVATE_GRAPHQL=http://localhost:3000/api/private/non-interactive/graphql
AUTH_ORY_KRATOS_PUBLIC_BASE_URL=http://localhost:3000/ory/kratos/public
AUTH_ADMIN_EMAIL=master-admin@alkem.io
AUTH_ADMIN_PASSWORD=master-password

# OpenAI Assistant only
# (api_key and assistant_id come per-request via externalConfig)
RUN_POLL_TIMEOUT_SECONDS=300
```

### 4. Run a Plugin

```bash
# Run with Poetry
poetry run python main.py

# Or activate the virtualenv first
poetry shell
python main.py
```

The process will:
1. Load config from environment variables
2. Discover and register the plugin specified by `PLUGIN_TYPE`
3. Resolve and inject port dependencies (adapters)
4. Call `plugin.startup()`
5. Start consuming messages from the configured RabbitMQ queue
6. Start the health server on port 8080

### 5. Verify It's Running

```bash
# Liveness check
curl http://localhost:8080/healthz

# Readiness check
curl http://localhost:8080/readyz
```

## Running Tests

```bash
# All tests
poetry run pytest

# With coverage
poetry run pytest --cov=core --cov=plugins --cov-report=term-missing

# Specific test file
poetry run pytest tests/core/test_registry.py

# Specific plugin tests
poetry run pytest tests/plugins/test_expert.py
```

## Linting and Type Checking

```bash
# Linting
poetry run flake8 core/ plugins/ tests/

# Type checking
poetry run pyright core/ plugins/
```

## Running All Plugins Locally (Docker Compose)

```bash
# Build the image
docker build -t alkemio/virtual-contributor:local .

# Start all plugins + infrastructure
docker-compose up
```

This starts one container per plugin type, all using the same image with different `PLUGIN_TYPE` values.

## Project Layout

```
core/           # Core system: ports, adapters, domain, events, config, registry, router
plugins/        # Plugin implementations (one per VC type)
tests/          # Test suite (mirrors source layout)
docs/           # PRD, ADRs
main.py         # Single entry point
```

See [plan.md](plan.md) for the complete directory tree.

## Adding a New Plugin

1. Create `plugins/{name}/plugin.py` implementing `PluginContract`
2. Declare port dependencies as constructor parameters
3. Add tests in `tests/plugins/test_{name}.py`
4. Set `PLUGIN_TYPE={name}` and run

No core code changes required. See [contracts/plugin-contract.md](contracts/plugin-contract.md) for the full contract specification.
