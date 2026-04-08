# Plan: Consistent Summarization Behavior Between ingest-website and ingest-space

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08

## Architecture

No architectural changes. This is a behavioral alignment fix within the existing plugin + config layer.

## Affected Modules

| Module | Change |
|--------|--------|
| `core/config.py` | Add `summarize_enabled: bool = True` to `BaseConfig`. Add validation for `summarize_concurrency >= 0`. |
| `plugins/ingest_website/plugin.py` | Remove conditional `if config.summarize_concurrency > 0` guard. Always include summary steps when `summarize_enabled` is true. Map `concurrency=0` to `concurrency=1`. Use `IngestWebsiteConfig`. |
| `plugins/ingest_space/plugin.py` | Read `summarize_concurrency` and `summarize_enabled` from config. Conditionally include summary steps. Map `concurrency=0` to `concurrency=1`. Use `IngestSpaceConfig`. |
| `tests/plugins/test_ingest_website.py` | Update existing test, add new tests for summarize_enabled flag and concurrency=0 behavior. |
| `tests/plugins/test_ingest_space.py` | Add tests for summarize_enabled flag and concurrency from config. |
| `tests/core/test_config_validation.py` | Add test for negative `summarize_concurrency` rejection and `summarize_enabled` defaults. |

## Data Model Deltas

None. No database/store schema changes.

## Interface Contracts

No port or protocol changes. The `DocumentSummaryStep` constructor already accepts `concurrency: int`. The only change is what values the callers pass.

## Config Changes

```python
# core/config.py — BaseConfig
summarize_enabled: bool = True      # NEW: controls whether summary steps are included
summarize_concurrency: int = 8      # EXISTING: unchanged default, but 0 now means sequential
```

Validation addition: `summarize_concurrency >= 0` (reject negative values).

## Concurrency Mapping Logic (shared by both plugins)

```python
effective_concurrency = max(config.summarize_concurrency, 1)
```

This ensures `0` maps to `1` (sequential) and positive values pass through unchanged.

## Test Strategy

1. **Unit tests (plugins):** For both `ingest-website` and `ingest-space`:
   - Default behavior: summary steps are included in pipeline.
   - `summarize_enabled=False`: summary steps are excluded.
   - `summarize_concurrency=0`: `DocumentSummaryStep` receives `concurrency=1`.

2. **Unit tests (config):**
   - `summarize_enabled` defaults to `True`.
   - Negative `summarize_concurrency` raises `ValueError`.

3. **Existing tests:** Must continue to pass. The existing `test_pipeline_composition` test in `test_ingest_website.py` sets `summarize_concurrency=0` and will need updating since that no longer disables summarization.

## Rollout Notes

- **Backward compatible:** Deployments not setting `SUMMARIZE_ENABLED` get `true` (current ingest-space behavior), which is the correct default.
- **Migration:** Deployments that relied on `SUMMARIZE_CONCURRENCY=0` to disable summarization in ingest-website must now set `SUMMARIZE_ENABLED=false` instead.
- **No database migration needed.**
