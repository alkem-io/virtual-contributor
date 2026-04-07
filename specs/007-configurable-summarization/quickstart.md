# Quickstart: Configurable Pipeline — Separate Summarization LLM and Externalized Retrieval Parameters

**Feature Branch**: `007-configurable-summarization`
**Date**: 2026-04-06

## What This Feature Does

Adds three categories of environment-variable-driven configuration to the virtual-contributor pipeline:

1. **Separate Summarization LLM** — use a cheaper model for document/BoK summarization during ingestion
2. **Per-Plugin Retrieval Parameters** — tune `n_results`, score thresholds, and context budget per plugin
3. **Summarization Chunk Threshold** — control the minimum chunk count before summarization triggers

All configuration is backward compatible: the system behaves identically to today when no new env vars are set.

## New Environment Variables

### Summarization LLM

```env
# All three required to activate a separate summarization LLM.
# If any are missing, the main LLM is used for summarization.
SUMMARIZE_LLM_PROVIDER=mistral         # mistral | openai | anthropic
SUMMARIZE_LLM_MODEL=mistral-small-latest
SUMMARIZE_LLM_API_KEY=your-api-key

# Optional tuning (defaults shown)
SUMMARIZE_LLM_TEMPERATURE=0.3          # Default when summarize LLM is active
SUMMARIZE_LLM_TIMEOUT=                 # Falls back to LLM_TIMEOUT if unset
```

### Per-Plugin Retrieval

```env
# Expert plugin (handles user questions via PromptGraph + single-collection RAG)
EXPERT_N_RESULTS=5                     # Chunks to retrieve from vector store
EXPERT_MIN_SCORE=0.0                   # Minimum relevance score (0.0 = no filtering)

# Guidance plugin (handles user questions via multi-collection RAG)
GUIDANCE_N_RESULTS=5                   # Chunks to retrieve per collection
GUIDANCE_MIN_SCORE=0.0                 # Minimum relevance score (0.0 = no filtering)

# Context budget (applies to whichever plugin is active)
MAX_CONTEXT_CHARS=20000                # Max chars of context passed to LLM
```

### Summarization Threshold

```env
SUMMARY_CHUNK_THRESHOLD=4             # Docs with >= this many chunks get summarized
```

## Quick Verification

### 1. Verify summarization uses the configured model

```bash
# Set up a cheap summarization model
export SUMMARIZE_LLM_PROVIDER=mistral
export SUMMARIZE_LLM_MODEL=mistral-small-latest
export SUMMARIZE_LLM_API_KEY=your-key
export PLUGIN_TYPE=ingest-website

# Run the service and ingest a website
# Check logs for:
#   INFO: Summarization LLM configured: provider=mistral, model=mistral-small-latest
#   INFO: Summarizing document <id> (N chunks) [model=mistral-small-latest]
```

### 2. Verify retrieval parameter tuning

```bash
export EXPERT_N_RESULTS=8
export EXPERT_MIN_SCORE=0.3
export PLUGIN_TYPE=expert

# Query the expert plugin and observe:
# - 8 chunks requested from vector store (instead of default 5)
# - Chunks with score < 0.3 are filtered out
```

### 3. Verify context budget enforcement

```bash
export MAX_CONTEXT_CHARS=5000
export PLUGIN_TYPE=guidance

# Query the guidance plugin with a topic that returns many chunks
# Check logs for:
#   WARNING: Context budget exceeded: dropped N chunks (M chars)
```

## Files Changed

| File | Change |
|------|--------|
| `core/config.py` | Add summarize LLM fields, per-plugin retrieval fields, context budget, chunk threshold |
| `main.py` | Wire summarization LLM adapter; inject per-plugin retrieval config |
| `core/domain/pipeline/steps.py` | Accept configurable chunk threshold; add model logging |
| `core/adapters/langchain_llm.py` | Add token-usage logging at DEBUG level |
| `plugins/expert/plugin.py` | Add `max_context_chars` enforcement |
| `plugins/guidance/plugin.py` | Accept `n_results` parameter; add `max_context_chars` enforcement |
| `plugins/ingest_website/plugin.py` | Accept optional `summarize_llm` |
| `plugins/ingest_space/plugin.py` | Accept optional `summarize_llm` |
| `.env.example` | Document all new variables |

## Contracts

This feature does not change any external interfaces:

- **RabbitMQ event schemas**: Unchanged (no new fields in Input, Response, IngestWebsite, IngestBodyOfKnowledge)
- **LLMPort**: Unchanged (summarization LLM uses the same port)
- **KnowledgeStorePort**: Unchanged
- **PluginContract**: Unchanged (no new lifecycle methods)

No `contracts/` directory is generated because this is a purely internal configuration change with no external API surface modifications.
