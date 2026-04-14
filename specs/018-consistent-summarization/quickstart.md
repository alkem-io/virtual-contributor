# Quickstart: Consistent Summarization Behavior Between Ingest Plugins

**Feature Branch**: `story/1827-consistent-summarization-behavior`
**Date**: 2026-04-14

## What This Feature Does

Fixes inconsistent summarization behavior between ingest-website and ingest-space plugins:

1. **Explicit toggle** -- new `SUMMARIZE_ENABLED` flag (default `true`) controls whether summarization runs
2. **Consistent semantics** -- `SUMMARIZE_CONCURRENCY=0` means sequential execution, not "disabled"
3. **DI cleanup** -- ingest-website now uses constructor injection for config, matching ingest-space

All configuration is backward compatible: the system behaves identically when no new env vars are set.

## New Environment Variable

```env
# Explicitly enable/disable summarization in ingest pipelines.
# Default: true (backward compatible with current ingest-space behavior).
SUMMARIZE_ENABLED=true
```

## Quick Verification

### 1. Default behavior (no change from current ingest-space)

```bash
# SUMMARIZE_ENABLED is not set -- defaults to true
export PLUGIN_TYPE=ingest-space
poetry run python main.py
# Both DocumentSummaryStep and BodyOfKnowledgeSummaryStep are included
```

### 2. Disable summarization

```bash
export SUMMARIZE_ENABLED=false
export PLUGIN_TYPE=ingest-website
poetry run python main.py
# Neither DocumentSummaryStep nor BodyOfKnowledgeSummaryStep are included
```

### 3. Sequential summarization (concurrency=0)

```bash
export SUMMARIZE_ENABLED=true
export SUMMARIZE_CONCURRENCY=0
export PLUGIN_TYPE=ingest-website
poetry run python main.py
# DocumentSummaryStep runs with concurrency=1 (sequential)
# Previously, ingest-website would have skipped summarization entirely
```

### 4. Run tests

```bash
# All tests, including new summarization behavior tests
poetry run pytest tests/plugins/test_ingest_website.py tests/plugins/test_ingest_space.py tests/core/test_config_validation.py -v
```

## Files Changed

| File | Change |
|------|--------|
| `core/config.py` | Add `summarize_enabled: bool = True` field; add `summarize_concurrency >= 0` validation |
| `main.py` | Inject `summarize_enabled` and `summarize_concurrency` into plugins via constructor |
| `plugins/ingest_website/plugin.py` | Accept new constructor params; remove inline `BaseConfig()`; conditional step inclusion |
| `plugins/ingest_space/plugin.py` | Accept new constructor params; conditional step inclusion; explicit concurrency |
| `tests/core/test_config_validation.py` | Tests for concurrency validation and summarize_enabled defaults |
| `tests/plugins/test_ingest_website.py` | Three-scenario summarization tests; updated pipeline composition test |
| `tests/plugins/test_ingest_space.py` | Three-scenario summarization tests |

## Contracts

No external interface changes:
- **LLMPort**: Unchanged
- **PluginContract**: Unchanged (no new lifecycle methods)
- **Event schemas**: Unchanged
- **IngestEngine / PipelineStep**: Unchanged
