# Plan: Consistent summarization behavior between ingest-website and ingest-space

**Story:** #1827

## Architecture

No architectural changes. The fix operates entirely within the existing microkernel + hexagonal architecture. Changes are confined to:
- Configuration layer (`core/config.py`)
- Plugin wiring (`main.py`)
- Plugin implementations (`plugins/ingest_website/plugin.py`, `plugins/ingest_space/plugin.py`)
- Tests

## Affected Modules

### 1. `core/config.py` -- Add `summarize_enabled` field
- Add `summarize_enabled: bool = True` to `BaseConfig`.
- Add validation for `summarize_concurrency >= 0`.
- No changes to `IngestSpaceConfig` or `IngestWebsiteConfig`.

### 2. `main.py` -- Inject summarize_enabled and summarize_concurrency
- Inject `summarize_enabled` and `summarize_concurrency` into ingest plugins via constructor, following the existing pattern for `chunk_threshold`.
- The effective concurrency is `max(1, config.summarize_concurrency)` when summarization is enabled.

### 3. `plugins/ingest_website/plugin.py` -- Align with ingest-space
- Add `summarize_enabled: bool = True` and `summarize_concurrency: int = 8` constructor parameters.
- Remove inline `BaseConfig()` instantiation.
- Conditionally include summary steps based on `summarize_enabled`, not `summarize_concurrency`.
- Pass effective concurrency to `DocumentSummaryStep`.

### 4. `plugins/ingest_space/plugin.py` -- Add summarize_enabled guard
- Add `summarize_enabled: bool = True` and `summarize_concurrency: int = 8` constructor parameters.
- Conditionally include summary steps based on `summarize_enabled`.
- Pass `summarize_concurrency` to `DocumentSummaryStep`.

### 5. Tests
- Update `test_ingest_website.py::TestIngestWebsitePlugin::test_pipeline_composition` to not depend on `summarize_concurrency=0` skipping steps.
- Add tests for both plugins covering: enabled+concurrent, enabled+sequential (concurrency=0), disabled.

## Data Model Deltas

None. No changes to event models, Pydantic schemas, or stored data.

## Interface Contracts

### Plugin constructor changes

**IngestWebsitePlugin.__init__**:
- Add: `summarize_enabled: bool = True`
- Add: `summarize_concurrency: int = 8`

**IngestSpacePlugin.__init__**:
- Add: `summarize_enabled: bool = True`
- Add: `summarize_concurrency: int = 8`

### Config additions

**BaseConfig**:
- Add: `summarize_enabled: bool = True`
- Add: validation rule `summarize_concurrency >= 0`

## Test Strategy

1. **Unit tests for ingest-website**: Verify pipeline step composition under three scenarios (enabled+concurrent, enabled+sequential, disabled).
2. **Unit tests for ingest-space**: Verify pipeline step composition under the same three scenarios.
3. **Config validation test**: Verify that `summarize_concurrency < 0` raises `ValidationError`.
4. **Backward compatibility**: Verify that no existing test is broken when `summarize_enabled` is not explicitly set (defaults to True).

## Rollout Notes

- **Backward compatible**: Existing deployments without `SUMMARIZE_ENABLED` env var will see `summarize_enabled=True`, preserving current behavior for ingest-space and fixing the silent skip for ingest-website.
- **Breaking change for `summarize_concurrency=0` users**: If anyone was relying on `summarize_concurrency=0` to disable summarization in ingest-website, they must now set `SUMMARIZE_ENABLED=false` instead. This is the intended fix per the issue description.
