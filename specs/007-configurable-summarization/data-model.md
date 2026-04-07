# Data Model: Configurable Pipeline — Separate Summarization LLM and Externalized Retrieval Parameters

**Feature Branch**: `007-configurable-summarization`
**Date**: 2026-04-06

## Overview

This feature adds configuration fields only — no new database tables, no new event schemas, no new domain entities. All changes are additive fields on the existing `BaseConfig` (pydantic-settings) class.

## Entity: BaseConfig (modified)

**File**: `core/config.py`
**Type**: Pydantic Settings model (environment variable binding)

### New Fields — Summarization LLM

| Field | Type | Default | Env Var | Validation | Description |
|-------|------|---------|---------|------------|-------------|
| `summarize_llm_provider` | `LLMProvider \| None` | `None` | `SUMMARIZE_LLM_PROVIDER` | Enum: mistral, openai, anthropic | Provider for summarization LLM |
| `summarize_llm_model` | `str \| None` | `None` | `SUMMARIZE_LLM_MODEL` | — | Model name for summarization |
| `summarize_llm_api_key` | `str \| None` | `None` | `SUMMARIZE_LLM_API_KEY` | — | API key for summarization LLM |
| `summarize_llm_temperature` | `float \| None` | `None` | `SUMMARIZE_LLM_TEMPERATURE` | 0.0–2.0 | Temperature (defaults to 0.3 when summarize LLM is active but this field is unset) |
| `summarize_llm_timeout` | `int \| None` | `None` | `SUMMARIZE_LLM_TIMEOUT` | > 0 | Timeout in seconds (falls back to `llm_timeout` if unset) |

**Activation rule**: Summarization LLM is active when ALL THREE of `summarize_llm_provider`, `summarize_llm_model`, and `summarize_llm_api_key` are set.

**Fallback**: When not active, summarization uses the main LLM (`llm_provider`/`llm_model`/`llm_api_key`).

**Partial config warning**: When 1 or 2 (but not all 3) are set, log WARNING listing missing variables. Fall back to main LLM.

### New Fields — Per-Plugin Retrieval Parameters

| Field | Type | Default | Env Var | Validation | Description |
|-------|------|---------|---------|------------|-------------|
| `expert_n_results` | `int` | `5` | `EXPERT_N_RESULTS` | > 0 | Number of chunks to retrieve in expert plugin |
| `expert_min_score` | `float` | `0.3` | `EXPERT_MIN_SCORE` | 0.0–1.0 | Minimum relevance score for expert plugin |
| `guidance_n_results` | `int` | `5` | `GUIDANCE_N_RESULTS` | > 0 | Number of chunks per collection in guidance plugin |
| `guidance_min_score` | `float` | `0.3` | `GUIDANCE_MIN_SCORE` | 0.0–1.0 | Minimum relevance score for guidance plugin |

### New Fields — Context Budget

| Field | Type | Default | Env Var | Validation | Description |
|-------|------|---------|---------|------------|-------------|
| `max_context_chars` | `int` | `20000` | `MAX_CONTEXT_CHARS` | > 0 | Max character budget for retrieved context passed to LLM |

### New Fields — Summarization Threshold

| Field | Type | Default | Env Var | Validation | Description |
|-------|------|---------|---------|------------|-------------|
| `summary_chunk_threshold` | `int` | `4` | `SUMMARY_CHUNK_THRESHOLD` | > 0 | Minimum chunk count to trigger document summarization (docs with >= this many chunks are summarized) |

### Existing Fields (deprecated but preserved)

| Field | Type | Default | Env Var | Notes |
|-------|------|---------|---------|-------|
| `retrieval_n_results` | `int` | `5` | `RETRIEVAL_N_RESULTS` | Deprecated — use `EXPERT_N_RESULTS` / `GUIDANCE_N_RESULTS` instead. Kept for backward compatibility. |
| `retrieval_score_threshold` | `float` | `0.3` | `RETRIEVAL_SCORE_THRESHOLD` | Deprecated — use `EXPERT_MIN_SCORE` / `GUIDANCE_MIN_SCORE` instead. Kept for backward compatibility. |

### Validation Rules (model_validator)

1. **Summarize temperature**: If `summarize_llm_temperature` is set, must be 0.0–2.0.
2. **Summarize timeout**: If `summarize_llm_timeout` is set, must be > 0.
3. **Per-plugin n_results**: `expert_n_results` and `guidance_n_results` must be > 0.
4. **Per-plugin min_score**: `expert_min_score` and `guidance_min_score` must be 0.0–1.0.
5. **Context budget**: `max_context_chars` must be > 0. Log warning if < 1000.
6. **Chunk threshold**: `summary_chunk_threshold` must be > 0.
7. **Partial summarize config**: If 1 or 2 (but not all 3) of `summarize_llm_provider`, `summarize_llm_model`, `summarize_llm_api_key` are set, log WARNING (not an error — falls back to main LLM).

## Entity: DocumentSummaryStep (modified)

**File**: `core/domain/pipeline/steps.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `chunk_threshold` | `int` | `4` | Minimum number of chunks a document must have for summarization to trigger |

### Changed Behavior

- Current: `if len(doc_chunks) > 3` (hardcoded)
- New: `if len(doc_chunks) >= self._chunk_threshold`
- With default 4: `>= 4` is equivalent to `> 3` (backward compatible)

## Entity: IngestWebsitePlugin (modified)

**File**: `plugins/ingest_website/plugin.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `summarize_llm` | `LLMPort \| None` | `None` | Optional separate LLM for summarization. When None, uses the main LLM. |

### Changed Behavior

- Summary steps receive `summarize_llm or self._llm` as `llm_port`

## Entity: IngestSpacePlugin (modified)

**File**: `plugins/ingest_space/plugin.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `summarize_llm` | `LLMPort \| None` | `None` | Optional separate LLM for summarization. When None, uses the main LLM. |

### Changed Behavior

- Summary steps receive `summarize_llm or self._llm` as `llm_port`

## Entity: GuidancePlugin (modified)

**File**: `plugins/guidance/plugin.py`

### New Constructor Parameter

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `n_results` | `int` | `5` | Number of chunks to retrieve per collection |

### Changed Behavior

- Query calls use `self._n_results` instead of hardcoded `5`
- Dedup limit uses `self._n_results` instead of hardcoded `5`

## Entity: ExpertPlugin (unchanged)

Already accepts `n_results` and `score_threshold` in constructor. No changes needed.

## Context Budget Enforcement (new behavior in both retrieval plugins)

Both `ExpertPlugin` and `GuidancePlugin` gain context budget enforcement:

1. After score filtering, measure total character count of remaining chunks
2. If total exceeds `max_context_chars`, sort by score descending
3. Accumulate chunks until adding the next would exceed budget
4. Drop remaining lowest-scoring chunks
5. Log WARNING: "Context budget exceeded: dropped {N} chunks ({chars_dropped} chars)"

The `max_context_chars` value is injected via constructor (same pattern as `n_results` and `score_threshold`).

## Relationships

```text
BaseConfig
  ├── creates → main LLM adapter (via create_llm_adapter)
  ├── creates → summarization LLM adapter (via create_llm_adapter, when configured)
  ├── injects → ExpertPlugin(n_results, score_threshold, max_context_chars)
  ├── injects → GuidancePlugin(n_results, score_threshold, max_context_chars)
  ├── injects → IngestWebsitePlugin(summarize_llm)
  ├── injects → IngestSpacePlugin(summarize_llm)
  └── injects → DocumentSummaryStep(chunk_threshold) via ingest plugins

DocumentSummaryStep
  └── uses → summarize_llm or main LLM (via llm_port parameter)

BodyOfKnowledgeSummaryStep
  └── uses → summarize_llm or main LLM (via llm_port parameter)
```

## State Transitions

No state machines affected. All changes are configuration-at-startup. No runtime state transitions.
