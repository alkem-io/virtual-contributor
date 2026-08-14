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

## Faithfulness validation

When `FAITHFULNESS_VALIDATION_ENABLED=true`, each generated answer is checked
against the context it was produced from, and a warning is logged when the
answer **asserts** something after retrieval returned **nothing**.

**Observation only** — the answer a member receives is never changed, delayed,
or withheld. Off by default; disabled, no validator is constructed at all.

See `docs/adr/0017-post-generation-faithfulness-validation.md` for why
word-overlap scoring was rejected (it cannot separate a fabrication from a
faithful paraphrase, and would flag every non-English answer).

Both generation paths are covered: `_handle_simple` and the graph path. The
graph path returns no sources by design, which is why the check keys off the
context string rather than `Response.sources` — a sources-keyed check would
flag every graph answer.
