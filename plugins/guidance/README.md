# Guidance Plugin

Multi-collection RAG that queries three Alkemio knowledge bases in parallel for platform guidance answers.

## Overview

| Property | Value |
|----------|-------|
| **Plugin type** | `guidance` |
| **Event type** | `Input` |
| **Queue** | `virtual-contributor-engine-guidance` |
| **Ports** | `LLMPort`, `KnowledgeStorePort` |

## How It Works

Queries three fixed knowledge collections in parallel, merges and deduplicates results, then invokes the LLM with scored context.

```
Query
  → Parallel query across 3 collections:
  │   ├── alkem.io-knowledge
  │   ├── welcome.alkem.io-knowledge
  │   └── www.alkemio.org-knowledge
  → Merge results
  → Deduplicate by source URL (keep highest score per page)
  → Filter by score threshold (default 0.3)
  → Enforce context budget (default 20,000 chars)
  → Format as [source:N] tagged context blocks
  → LLM invocation (expects structured JSON response)
  → Parse JSON response → Extract answer + sources → Response
```

The LLM is prompted to respond in structured JSON format. The plugin parses JSON from the response, handling fenced code blocks, bare objects, and preamble/trailing text.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `GUIDANCE_N_RESULTS` | `5` | Number of chunks per collection |
| `GUIDANCE_MIN_SCORE` | `0.3` | Minimum relevance score threshold |
| `MAX_CONTEXT_CHARS` | `20000` | Context budget — lowest-scoring chunks dropped first |

Per-plugin LLM overrides are supported via `GUIDANCE_LLM_*` prefix.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.py` | Plugin implementation — parallel multi-collection query, dedup, JSON response parsing |
| `prompts.py` | System prompt with JSON response format instructions |

## Testing

```bash
poetry run pytest tests/plugins/test_guidance.py
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

Width applies at **both** points this plugin uses it: the per-collection query
and the post-dedupe truncation. Applying it at only the first would fetch the
extra evidence and then discard it, so widening would be invisible in the
answer — covered by `tests/plugins/test_guidance_routing.py`.
