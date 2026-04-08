# Quickstart: BoK LLM, Summarize Base URL, and LLM Factory Hardening

**Feature Branch**: `develop`
**Date**: 2026-04-08

## What This Feature Does

Adds three improvements to the LLM configuration for ingest pipelines:

1. **BoK LLM** — a separate, large-context-window model for body-of-knowledge summarization
2. **Summarize LLM Base URL** — point the summarization LLM to a local model server
3. **LLM Factory Hardening** — suppress Qwen3 chain-of-thought, fix Mistral-only keepalive

All configuration is backward compatible: the system behaves identically when no new env vars are set.

## New Environment Variables

### BoK LLM

```env
# All three required to activate a separate BoK LLM.
# Falls back to summarize LLM, then main LLM.
BOK_LLM_PROVIDER=              # mistral | openai | anthropic
BOK_LLM_MODEL=                 # e.g., mistral-large-latest (128K context)
BOK_LLM_API_KEY=

# Optional
BOK_LLM_BASE_URL=              # Override endpoint (e.g., local vLLM)
BOK_LLM_TEMPERATURE=           # Default: 0.3 when active
BOK_LLM_TIMEOUT=               # Default: LLM_TIMEOUT
```

### Summarize LLM Base URL

```env
# Optional: override endpoint for summarization LLM
SUMMARIZE_LLM_BASE_URL=        # e.g., http://localhost:8000/v1
```

## Quick Verification

### 1. Three-tier LLM setup

```bash
# Main LLM (user-facing)
export LLM_PROVIDER=openai
export LLM_MODEL=gpt-4o
export LLM_API_KEY=sk-main

# Summarization LLM (per-document, cheap)
export SUMMARIZE_LLM_PROVIDER=mistral
export SUMMARIZE_LLM_MODEL=mistral-small-latest
export SUMMARIZE_LLM_API_KEY=ms-key

# BoK LLM (aggregated summary, large context)
export BOK_LLM_PROVIDER=mistral
export BOK_LLM_MODEL=mistral-large-latest
export BOK_LLM_API_KEY=ml-key

export PLUGIN_TYPE=ingest-space
poetry run python main.py

# Check logs for:
#   INFO: Summarization LLM configured: provider=mistral, model=mistral-small-latest, base_url=(inherited from main LLM)
#   INFO: BoK LLM configured: provider=mistral, model=mistral-large-latest, base_url=(inherited from main LLM)
```

### 2. Local model with base URL

```bash
export SUMMARIZE_LLM_PROVIDER=openai
export SUMMARIZE_LLM_MODEL=Qwen/Qwen3-8B
export SUMMARIZE_LLM_API_KEY=not-needed
export SUMMARIZE_LLM_BASE_URL=http://localhost:8000/v1

# Summarization calls go to local vLLM, with thinking disabled automatically
```

### 3. Fallback verification

```bash
# Only set summarize LLM, no BoK LLM
export SUMMARIZE_LLM_PROVIDER=mistral
export SUMMARIZE_LLM_MODEL=mistral-small-latest
export SUMMARIZE_LLM_API_KEY=key

# BoK summarization falls back to summarize LLM
# No BoK LLM log line appears at startup
```

## Files Changed

| File | Change |
|------|--------|
| `core/config.py` | Add `bok_llm_*` fields (6) and `summarize_llm_base_url` |
| `core/provider_factory.py` | Add `disable_thinking` param; Mistral-only keepalive; tighter `hasattr` |
| `main.py` | BoK LLM creation/wiring/logging; summarize base_url; `disable_thinking=True` |
| `plugins/ingest_space/plugin.py` | Accept `bok_llm`, route to `BodyOfKnowledgeSummaryStep` |
| `plugins/ingest_website/plugin.py` | Accept `bok_llm`, route to `BodyOfKnowledgeSummaryStep` |
| `.env.example` | Document `BOK_LLM_*` and `SUMMARIZE_LLM_BASE_URL` |

## Contracts

No external interface changes:
- **LLMPort**: Unchanged (BoK LLM uses the same port)
- **PluginContract**: Unchanged (no new lifecycle methods)
- **Event schemas**: Unchanged
