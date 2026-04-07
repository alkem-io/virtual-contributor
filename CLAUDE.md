# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Dependencies
poetry install

# Run a specific plugin locally
PLUGIN_TYPE=generic poetry run python main.py

# Tests
poetry run pytest                                              # All tests
poetry run pytest tests/plugins/test_expert.py                 # Single file
poetry run pytest tests/plugins/test_expert.py::test_handle    # Single test
poetry run pytest --cov=core --cov=plugins --cov-report=term-missing  # Coverage

# Lint & type check
poetry run ruff check core/ plugins/ tests/
poetry run pyright core/ plugins/
```

Tests use `asyncio_mode = "auto"` (pyproject.toml) — async test functions run automatically without `@pytest.mark.asyncio`.

## Architecture

**Microkernel + Hexagonal (Ports and Adapters)**. Consolidates 7 formerly standalone services into one Python 3.12 codebase.

### Core (`core/`)

- **Ports** (`core/ports/`): `@runtime_checkable` Protocol classes — `LLMPort`, `EmbeddingsPort`, `KnowledgeStorePort`, `TransportPort`. Plugins depend on these, never on concrete adapters.
- **Adapters** (`core/adapters/`): Concrete implementations — `LangChainLLMAdapter` (Mistral/OpenAI/Anthropic via `core/provider_factory.py`), `ChromaDBAdapter`, `RabbitMQAdapter`, embedding adapters.
- **Container** (`core/container.py`): IoC container. `resolve_for_plugin(plugin_class)` introspects `__init__` type hints to auto-inject only the ports a plugin needs.
- **Registry** (`core/registry.py`): Discovers plugins by importing `plugins.{plugin_type}.plugin` and finding the class with `name` + `event_type` attributes.
- **Router** (`core/router.py`): Content-based message routing — `parse_event()` dispatches to the correct Pydantic event model, `build_response_envelope()` wraps the response.
- **Config** (`core/config.py`): Pydantic Settings with env var binding. Per-plugin LLM overrides via `{PLUGIN_NAME}_LLM_*` env var prefix. Separate `summarize_llm_*` settings for ingest pipelines.

### Plugins (`plugins/`)

No base class — duck-typed `PluginContract` protocol:
```python
class PluginContract(Protocol):
    name: str
    event_type: type
    async def startup() -> None: ...
    async def shutdown() -> None: ...
    async def handle(event) -> Response: ...
```

| Plugin | Purpose |
|--------|---------|
| `expert` | PromptGraph (LangGraph) + single-collection RAG retrieval |
| `generic` | Direct LLM with optional history condensation |
| `guidance` | Multi-collection RAG (3 Alkemio knowledge bases in parallel) |
| `openai_assistant` | OpenAI Assistants API with thread management |
| `ingest_website` | Web crawler → chunk → hash → embed → store pipeline |
| `ingest_space` | Alkemio GraphQL space tree → same ingest pipeline |

### Message Flow

```
RabbitMQ → Router.parse_event(body) → Plugin.handle(event) → Router.build_response_envelope() → RabbitMQ
```

### Domain (`core/domain/`)

- **Pipeline engine** (`pipeline/engine.py`): Ordered step executor for ingest. Steps (`pipeline/steps.py`): Chunk → ContentHash → ChangeDetection → Summarize → Embed → Store → OrphanCleanup.
- **PromptGraph** (`prompt_graph.py`): Compiles JSON graph definitions into LangGraph `StateGraph`. Nodes have prompt templates, input variables, and optional Pydantic output schemas.
- **Ingest models** (`ingest_pipeline.py`): `Document`, `Chunk`, `DocumentMetadata`, `IngestResult`.

### Events (`core/events/`)

Pydantic models with camelCase aliases (wire format). Key types: `Input` (queries), `Response` + `Source` (answers), `IngestWebsite`, `IngestBodyOfKnowledge`.

### Startup (`main.py`)

Config → logging → plugin discovery → adapter wiring (via container) → plugin startup → RabbitMQ consume loop → health server on `:8080` (`/healthz`, `/readyz`).

## Testing Conventions

- Mock ports in `tests/conftest.py`: `MockLLMPort`, `MockEmbeddingsPort`, `MockKnowledgeStorePort` — in-memory implementations with call tracking.
- Event factories: `make_input(...)`, `make_ingest_website(...)` for building test events with sensible defaults.
- Plugin tests instantiate with mock ports, call `handle()`, and assert on LLM calls, knowledge store queries, and response content.

## Key Design Decisions

- `docs/adr/` contains Architecture Decision Records (microkernel, plugin contract, unified LLM adapter, content hash dedup).
- All I/O is async; sync LangChain LLM calls are wrapped with `asyncio.to_thread`.
- LLM retries: 3 attempts with exponential backoff (1s base).
- RAG context budget: `max_context_chars` (default 20000) drops lowest-scoring chunks first.
- Content deduplication: SHA-256 hashes on chunks, with change detection and orphan cleanup during ingest.
