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
