# Data Model: Consistent Summarization Behavior Between Ingest Plugins

**Feature Branch**: `story/1827-consistent-summarization-behavior`
**Date**: 2026-04-14

## Overview

This feature adds one configuration field and one validation rule to `BaseConfig`, and modifies constructor signatures for both ingest plugins. No new database tables, event schemas, or domain entities. No changes to stored data or wire format.

## Entity: BaseConfig (modified)

**File**: `core/config.py`

### New Field

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `summarize_enabled` | `bool` | `True` | `SUMMARIZE_ENABLED` | Controls whether summarization steps are included in ingest pipelines |

### New Validation

| Rule | Description |
|------|-------------|
| `summarize_concurrency >= 0` | Rejects negative concurrency values at config load time with error: "SUMMARIZE_CONCURRENCY must be >= 0, got {value}" |

### Existing Field (behavior change)

| Field | Type | Default | Env Var | Behavior Change |
|-------|------|---------|---------|-----------------|
| `summarize_concurrency` | `int` | `8` | `SUMMARIZE_CONCURRENCY` | Value `0` no longer means "disabled" in ingest-website. Instead, plugins apply `max(1, value)` for effective concurrency |

## Entity: IngestWebsitePlugin (modified)

**File**: `plugins/ingest_website/plugin.py`

### New Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `summarize_enabled` | `bool` | `True` | Whether to include summarization steps in the pipeline |
| `summarize_concurrency` | `int` | `8` | Concurrency for DocumentSummaryStep. Stored as `max(1, value)` |

### Removed Dependencies

- Removed inline `from core.config import BaseConfig` inside `handle()`
- Removed `config = BaseConfig()` instantiation inside `handle()`

### Changed Behavior

- Pipeline step inclusion now governed by `self._summarize_enabled` instead of `config.summarize_concurrency > 0`
- Concurrency passed to DocumentSummaryStep is `self._summarize_concurrency` (already normalized via `max(1, ...)`)

## Entity: IngestSpacePlugin (modified)

**File**: `plugins/ingest_space/plugin.py`

### New Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `summarize_enabled` | `bool` | `True` | Whether to include summarization steps in the pipeline |
| `summarize_concurrency` | `int` | `8` | Concurrency for DocumentSummaryStep. Stored as `max(1, value)` |

### Changed Behavior

- Pipeline step inclusion now governed by `self._summarize_enabled`
- Previously, summary steps were always included unconditionally
- Concurrency parameter now explicitly passed to DocumentSummaryStep

## Entity: main.py _run() (modified)

**File**: `main.py`

### New Injection Logic

| Injected Parameter | Source | Condition |
|--------------------|--------|-----------|
| `summarize_enabled` | `config.summarize_enabled` | `"summarize_enabled" in sig.parameters` |
| `summarize_concurrency` | `config.summarize_concurrency` | `"summarize_concurrency" in sig.parameters` |

Follows the same pattern as existing `chunk_threshold` injection.

## Relationships

```text
BaseConfig
  ├── provides → summarize_enabled (bool)
  ├── provides → summarize_concurrency (int, validated >= 0)
  ├── injects → IngestWebsitePlugin(summarize_enabled, summarize_concurrency)
  └── injects → IngestSpacePlugin(summarize_enabled, summarize_concurrency)

IngestWebsitePlugin / IngestSpacePlugin
  ├── stores → self._summarize_enabled
  ├── stores → self._summarize_concurrency = max(1, concurrency)
  ├── when enabled → includes DocumentSummaryStep(concurrency=self._summarize_concurrency)
  ├── when enabled → includes BodyOfKnowledgeSummaryStep
  └── when disabled → skips both summary steps
```

## State Transitions

No state machines affected. Configuration is resolved at startup/plugin construction time. The `summarize_enabled` flag is read once when the plugin is constructed and does not change at runtime.
