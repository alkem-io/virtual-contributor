# Plan: Consistent Summarization Behavior Between ingest-website and ingest-space

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08

## Architecture

No new modules or services. This is a behavioral alignment change across two existing plugins plus a config addition. The hexagonal architecture is preserved -- config is injected, plugins compose their own pipelines.

## Affected Modules

### 1. `core/config.py`
- Add `summarize_enabled: bool = True` field to `BaseConfig`.
- Add validation: `summarize_concurrency >= 0`.

### 2. `plugins/ingest_website/plugin.py`
- Add `summarize_enabled: bool` and `summarize_concurrency: int` constructor parameters (with defaults).
- Remove inline `from core.config import BaseConfig; config = BaseConfig()` from `handle()`.
- Conditionally include summary steps based on `self._summarize_enabled` (not concurrency).
- Pass `max(1, self._summarize_concurrency)` to `DocumentSummaryStep` to treat 0 as sequential.

### 3. `plugins/ingest_space/plugin.py`
- Add `summarize_enabled: bool` and `summarize_concurrency: int` constructor parameters (with defaults).
- Conditionally include summary steps based on `self._summarize_enabled`.
- Pass `max(1, self._summarize_concurrency)` to `DocumentSummaryStep`.

### 4. `main.py`
- Inject `summarize_enabled` and `summarize_concurrency` from config into ingest plugins via constructor kwargs, alongside existing `summarize_llm` and `chunk_threshold` injection.

### 5. `.env.example`
- Add `SUMMARIZE_ENABLED=true` with documentation comment.
- Add `SUMMARIZE_CONCURRENCY=8` (documenting the existing default explicitly).

### 6. Tests
- `tests/plugins/test_ingest_website.py`: Update existing `test_pipeline_composition` to no longer mock `summarize_concurrency=0` as disabling summarization. Add new tests for `summarize_enabled=True` and `summarize_enabled=False` pipeline composition.
- `tests/plugins/test_ingest_space.py`: Add tests for `summarize_enabled=True` and `summarize_enabled=False` pipeline composition.
- `tests/core/test_config_validation.py`: Add test for `summarize_concurrency` negative value validation and `summarize_enabled` field.

## Data Model Deltas

None. No database/store schema changes.

## Interface Contracts

### `IngestWebsitePlugin.__init__` (updated signature)
```python
def __init__(
    self,
    llm: LLMPort,
    embeddings: EmbeddingsPort,
    knowledge_store: KnowledgeStorePort,
    *,
    summarize_llm: LLMPort | None = None,
    chunk_threshold: int = 4,
    summarize_enabled: bool = True,
    summarize_concurrency: int = 8,
) -> None:
```

### `IngestSpacePlugin.__init__` (updated signature)
```python
def __init__(
    self,
    llm: LLMPort,
    embeddings: EmbeddingsPort,
    knowledge_store: KnowledgeStorePort,
    graphql_client: Any = None,
    *,
    summarize_llm: LLMPort | None = None,
    chunk_threshold: int = 4,
    summarize_enabled: bool = True,
    summarize_concurrency: int = 8,
) -> None:
```

### `BaseConfig` (new field)
```python
summarize_enabled: bool = True
```

## Test Strategy

1. **Unit tests -- plugin pipeline composition:** Verify that both plugins include/exclude summary steps based on `summarize_enabled`. Verify `summarize_concurrency=0` does not skip steps.
2. **Unit tests -- config validation:** Verify `summarize_concurrency` rejects negative values. Verify `summarize_enabled` accepts bool-like values.
3. **Regression:** All existing tests pass unmodified (except the one test that mocks `summarize_concurrency=0` to disable summarization -- that test's intent changes).

## Rollout Notes

- **Breaking change for `summarize_concurrency=0` users:** Users who previously set `SUMMARIZE_CONCURRENCY=0` to disable summarization in `ingest-website` must now use `SUMMARIZE_ENABLED=false`. The `SUMMARIZE_CONCURRENCY=0` setting will now mean "sequential" (concurrency=1).
- **Default behavior unchanged:** For users not setting `SUMMARIZE_CONCURRENCY=0`, behavior is identical. Both plugins will always include summary steps by default.
- **Helm/deployment:** If deployment configs set `SUMMARIZE_CONCURRENCY=0`, they need updating to `SUMMARIZE_ENABLED=false` to maintain the "no summarization" behavior.
