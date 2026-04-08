# Data Model: BoK LLM, Summarize Base URL, and LLM Factory Hardening

**Feature Branch**: `develop`
**Date**: 2026-04-08

## Overview

This feature adds configuration fields for a third LLM tier (BoK LLM) and a base URL for the summarization LLM. No new database tables, event schemas, or domain entities. All changes are additive fields on `BaseConfig`.

## Entity: BaseConfig (modified)

**File**: `core/config.py`

### New Fields — BoK LLM

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `bok_llm_provider` | `LLMProvider \| None` | `None` | `BOK_LLM_PROVIDER` | Provider for BoK summarization LLM |
| `bok_llm_model` | `str \| None` | `None` | `BOK_LLM_MODEL` | Model name for BoK summarization |
| `bok_llm_api_key` | `str \| None` | `None` | `BOK_LLM_API_KEY` | API key for BoK LLM |
| `bok_llm_base_url` | `str \| None` | `None` | `BOK_LLM_BASE_URL` | Base URL override for BoK LLM |
| `bok_llm_temperature` | `float \| None` | `None` | `BOK_LLM_TEMPERATURE` | Temperature (defaults to 0.3 when BoK LLM is active) |
| `bok_llm_timeout` | `int \| None` | `None` | `BOK_LLM_TIMEOUT` | Timeout in seconds (falls back to `LLM_TIMEOUT`) |

**Activation rule**: BoK LLM is active when ALL THREE of `bok_llm_provider`, `bok_llm_model`, and `bok_llm_api_key` are set.

**Fallback**: BoK LLM -> summarize LLM -> main LLM.

### New Field — Summarize LLM Base URL

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `summarize_llm_base_url` | `str \| None` | `None` | `SUMMARIZE_LLM_BASE_URL` | Base URL override for summarization LLM endpoint |

## Entity: create_llm_adapter (modified)

**File**: `core/provider_factory.py`

### New Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `disable_thinking` | `bool` | `False` | When True, sends `extra_body: {"chat_template_kwargs": {"enable_thinking": false}}` to suppress Qwen3 chain-of-thought |

### Changed Behavior — Mistral-only keepalive

- **Before**: httpx keep-alive disabling applied to all providers when `base_url` was set
- **After**: Only applied when `provider == LLMProvider.mistral` AND `hasattr(llm.async_client, "headers")`

## Entity: IngestSpacePlugin (modified)

**File**: `plugins/ingest_space/plugin.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bok_llm` | `LLMPort \| None` | `None` | Optional dedicated LLM for BoK summarization |

### Changed Behavior

- `BodyOfKnowledgeSummaryStep` receives `self._bok_llm or summary_llm` as `llm_port`
- Previously received `summary_llm` directly

## Entity: IngestWebsitePlugin (modified)

**File**: `plugins/ingest_website/plugin.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `bok_llm` | `LLMPort \| None` | `None` | Optional dedicated LLM for BoK summarization |

### Changed Behavior

- `BodyOfKnowledgeSummaryStep` receives `self._bok_llm or summary_llm` as `llm_port`
- Previously received `summary_llm` directly

## Relationships

```text
BaseConfig
  ├── creates → main LLM adapter (via create_llm_adapter)
  ├── creates → summarization LLM adapter (via create_llm_adapter, disable_thinking=True)
  ├── creates → BoK LLM adapter (via create_llm_adapter, disable_thinking=True)
  ├── injects → IngestWebsitePlugin(summarize_llm, bok_llm)
  └── injects → IngestSpacePlugin(summarize_llm, bok_llm)

BodyOfKnowledgeSummaryStep
  └── uses → bok_llm or summarize_llm or main LLM (via llm_port)

DocumentSummaryStep
  └── uses → summarize_llm or main LLM (via llm_port, unchanged)
```

## State Transitions

No state machines affected. Configuration and fallback resolved at startup/plugin construction.
