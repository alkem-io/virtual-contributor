# Plan: Consistent Summarization Behavior Between Ingest Plugins

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08

## Architecture

No new modules or architectural changes. This is a behavior alignment fix across two existing plugins, plus one new config field.

### Affected Modules

| Module | Change |
|--------|--------|
| `core/config.py` | Add `summarize_enabled: bool = True` field to `BaseConfig` |
| `plugins/ingest_website/plugin.py` | Accept `summarize_enabled` and `summarize_concurrency` as constructor params; remove inline `BaseConfig()`; guard summary steps with `summarize_enabled` |
| `plugins/ingest_space/plugin.py` | Accept `summarize_enabled` and `summarize_concurrency` as constructor params; guard summary steps with `summarize_enabled`; pass concurrency to `DocumentSummaryStep` |
| `main.py` | Inject `summarize_enabled` and `summarize_concurrency` from config into ingest plugins |
| `.env.example` | Add `SUMMARIZE_ENABLED=true` documentation entry |
| `tests/plugins/test_ingest_website.py` | Add tests for `summarize_enabled=True` and `summarize_enabled=False` |
| `tests/plugins/test_ingest_space.py` | Add tests for `summarize_enabled=True` and `summarize_enabled=False` |

### Data Model Deltas

- `BaseConfig` gains one new field: `summarize_enabled: bool = True`

### Interface Contracts

No port/adapter interface changes. Both plugins' `handle()` signatures remain unchanged.

### Behavioral Changes

**Before:**
- `ingest-website`: Skips both summary steps when `summarize_concurrency == 0`
- `ingest-space`: Always includes summary steps, does not read `summarize_concurrency`

**After:**
- Both plugins: Include summary steps when `summarize_enabled is True` (default)
- Both plugins: Omit summary steps when `summarize_enabled is False`
- Both plugins: Pass `summarize_concurrency` to `DocumentSummaryStep` (0 is normalized to 1)
- `ingest-space`: Now reads config and respects `summarize_enabled` and `summarize_concurrency`

### Concurrency normalization

In both plugins, when building the pipeline:
```python
concurrency = max(1, config.summarize_concurrency)
```
This ensures `0` becomes `1` (sequential) and any positive value is passed through.

## Test Strategy

1. **Unit tests for `ingest-website`:**
   - Pipeline includes summary steps when `summarize_enabled=True`
   - Pipeline excludes summary steps when `summarize_enabled=False`
   - `summarize_concurrency` is passed to `DocumentSummaryStep`

2. **Unit tests for `ingest-space`:**
   - Pipeline includes summary steps when `summarize_enabled=True`
   - Pipeline excludes summary steps when `summarize_enabled=False`
   - `summarize_concurrency` is passed to `DocumentSummaryStep`

3. **Config tests:**
   - `summarize_enabled` defaults to `True`
   - `summarize_enabled` can be set to `False` via env var

4. **Existing tests:** All must continue to pass unchanged.

## Rollout Notes

- **Zero-config deployment:** No env var changes needed. Default behavior matches current `ingest-space` behavior (summarization on).
- **Opt-out:** Set `SUMMARIZE_ENABLED=false` to disable summarization in both plugins.
- **Migration path:** Deployments using `SUMMARIZE_CONCURRENCY=0` to disable summarization in `ingest-website` should switch to `SUMMARIZE_ENABLED=false`. With this change, `SUMMARIZE_CONCURRENCY=0` will mean sequential processing, not disabled.
