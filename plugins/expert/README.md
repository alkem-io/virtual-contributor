# Expert Plugin

PromptGraph-based plugin with single-collection RAG retrieval for knowledge-grounded Q&A.

## Overview

| Property | Value |
|----------|-------|
| **Plugin type** | `expert` |
| **Event type** | `Input` |
| **Queue** | `virtual-contributor-engine-expert` |
| **Ports** | `LLMPort`, `KnowledgeStorePort` |

## How It Works

The expert plugin supports two execution modes:

### PromptGraph mode (primary)
When the incoming event includes a `prompt_graph` definition, the plugin compiles a LangGraph workflow from JSON. Graph nodes have prompt templates, input variables, and optional Pydantic output schemas. A special **retrieve** node is injected that queries the knowledge store and formats results with `[source:N]` attribution tags.

### Simple RAG mode (fallback)
When no graph is defined, falls back to direct knowledge retrieval + LLM invocation with the same score filtering and context budget enforcement.

## Retrieval Pipeline

```
Query → KnowledgeStore.query(collection, message, n_results)
  → Filter by score threshold (default 0.3)
  → Sort by score descending
  → Enforce context budget (default 20,000 chars, drop lowest-scoring first)
  → Format as [source:N] tagged context blocks
  → LLM invocation with context
  → Extract sources from metadata → Response
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPERT_N_RESULTS` | `5` | Number of chunks to retrieve |
| `EXPERT_MIN_SCORE` | `0.3` | Minimum relevance score threshold |
| `MAX_CONTEXT_CHARS` | `20000` | Context budget — lowest-scoring chunks dropped first |

Per-plugin LLM overrides are supported via `EXPERT_LLM_*` prefix.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.py` | Plugin implementation — graph and simple RAG execution, retrieval, source extraction |
| `prompts.py` | System prompt templates for RAG context formatting |

## Testing

```bash
poetry run pytest tests/plugins/test_expert.py
```

## Adaptive routing

When `ROUTING_ENABLED=true`, each question is classified before retrieval and
this plugin's retrieval width, score threshold and context budget come from the
matching profile instead of the configured constants.

| Route | Behaviour here |
|---|---|
| conversational | **no retrieval at all** — the store is not queried |
| simple | narrower retrieval than today |
| moderate | exactly today's behaviour (the fallback for unrecognised input) |
| complex | wider retrieval **and** a wider context budget |

**Off by default.** With routing disabled no classifier is injected and this
plugin takes its existing code path with its existing constants — that is the
rollback, and it is a config change rather than a deploy.

Classification is rule-based and in-process: no model, no network call,
sub-millisecond. See `docs/adr/0016-adaptive-query-routing.md` for why an LLM
classifier was rejected on arithmetic, and `README.md` for the settings.

Both retrieval sites route: `_handle_simple` and the `retrieve_node` closure
inside `_handle_with_graph`. The closure captures its settings from the
enclosing scope, so a change touching only one would leave graph-driven queries
on today's behaviour — covered by `tests/plugins/test_expert_routing.py`.
