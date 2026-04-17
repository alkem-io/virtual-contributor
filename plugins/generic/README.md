# Generic Plugin

Direct LLM invocation with optional chat history condensation.

## Overview

| Property | Value |
|----------|-------|
| **Plugin type** | `generic` |
| **Event type** | `Input` |
| **Queue** | `virtual-contributor-engine-generic` |
| **Ports** | `LLMPort` |

## How It Works

The simplest plugin in the system. Routes user messages directly to the LLM with no retrieval step.

```
Input event
  → (if history present) Condense conversation into standalone question via LLM
  → Build message array from system prompt + condensed question
  → LLM invocation
  → Response (no sources)
```

When conversation history is present, prior exchanges are condensed into a standalone question before the final LLM call. This prevents context window bloat from long conversation threads.

## Configuration

No plugin-specific configuration. Per-plugin LLM overrides are supported via `GENERIC_LLM_*` prefix.

The plugin also supports per-request engine selection via `input.engine` and `external_config.api_key` for dynamic LLM routing.

## Key Files

| File | Purpose |
|------|---------|
| `plugin.py` | Plugin implementation — history condensation and LLM invocation |
| `prompts.py` | Condensation prompt template |

## Testing

```bash
poetry run pytest tests/plugins/test_generic.py
```
