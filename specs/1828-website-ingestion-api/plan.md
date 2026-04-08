# Plan: First-class Website Ingestion API (VC Service Side)

**Story:** alkem-io/alkemio#1828
**Date:** 2026-04-08

## Architecture

### Affected Modules

1. **`core/events/ingest_website.py`** -- Event schema changes
2. **`plugins/ingest_website/crawler.py`** -- Crawler enhancements (maxDepth, patterns)
3. **`plugins/ingest_website/plugin.py`** -- Multi-source handling, mode support, metadata storage
4. **`core/events/__init__.py`** -- Re-export new types
5. **`tests/conftest.py`** -- Update `make_ingest_website` factory
6. **`tests/plugins/test_ingest_website.py`** -- New tests

### Unchanged Modules

- `core/router.py` -- No changes needed; already routes by `eventType`
- `core/config.py` -- No changes; `IngestWebsiteConfig.process_pages_limit` is already used as fallback
- `core/domain/pipeline/` -- No changes to pipeline engine or steps
- `core/ports/` -- No changes to port protocols
- All other plugins -- Unaffected

## Data Model Deltas

### New Event Models (`core/events/ingest_website.py`)

```python
class IngestionMode(str, Enum):
    FULL = "full"
    INCREMENTAL = "incremental"

class WebsiteSource(EventBase):
    url: str
    page_limit: int | None = Field(default=None, alias="pageLimit")
    max_depth: int = Field(default=-1, alias="maxDepth")
    include_patterns: list[str] | None = Field(default=None, alias="includePatterns")
    exclude_patterns: list[str] | None = Field(default=None, alias="excludePatterns")

class SourceResult(EventBase):
    url: str
    pages_processed: int = Field(default=0, alias="pagesProcessed")
    error: str = ""

class IngestWebsite(EventBase):
    # Legacy field (backward compat)
    base_url: str | None = Field(default=None, alias="baseUrl")
    # New fields
    sources: list[WebsiteSource] = Field(default_factory=list)
    mode: IngestionMode = Field(default=IngestionMode.INCREMENTAL)
    # Existing fields
    type: str = "website"
    purpose: str = "knowledge"
    persona_id: str = Field(alias="personaId")
    summarization_model: str = Field(default="mistral-medium", alias="summarizationModel")

    # model_validator: if sources is empty and base_url is set,
    # synthesize sources = [WebsiteSource(url=base_url)]

class IngestWebsiteResult(EventBase):
    timestamp: int
    result: IngestionResult
    error: str = ""
    source_results: list[SourceResult] = Field(default_factory=list, alias="sourceResults")
```

### Crawler API Change (`plugins/ingest_website/crawler.py`)

```python
async def crawl(
    base_url: str,
    page_limit: int = 20,
    max_depth: int = -1,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[dict]:
```

The BFS queue entries become `(url, depth)` tuples to track link depth.

## Interface Contracts

### Crawler

- `max_depth=-1` means unlimited (backward compat with current behavior)
- `max_depth=0` means base URL only
- `include_patterns=None` means no filtering (all same-domain pages allowed)
- `include_patterns=["pattern"]` means only URLs whose path matches at least one pattern
- `exclude_patterns=None` means no exclusions
- Exclude takes precedence over include
- Base URL always crawled regardless of patterns
- Patterns use `fnmatch` on URL path component

### Plugin

- `sources` list drives crawling; legacy `base_url` is normalized into `sources` by validator
- Collection name: `{personaId}-knowledge`
- FULL mode: `delete_collection()` before pipeline
- INCREMENTAL mode: existing pipeline (ChangeDetection + OrphanCleanup)
- Source config sentinel: stored as chunk `__source_config__` with JSON metadata
- Per-source `pageLimit=None` falls back to `IngestWebsiteConfig.process_pages_limit`

## Test Strategy

### Unit Tests (Crawler)

- `test_max_depth_zero` -- only base page crawled
- `test_max_depth_one` -- base + direct links, no deeper
- `test_max_depth_unlimited` -- default -1 follows all links
- `test_include_patterns` -- only matching paths crawled
- `test_exclude_patterns` -- matching paths skipped
- `test_exclude_overrides_include` -- exclude wins
- `test_base_url_always_crawled` -- even with restrictive include patterns

### Unit Tests (Event Model)

- `test_backward_compat_base_url_only` -- old format produces valid sources
- `test_sources_field` -- new format parsed correctly
- `test_mode_default_incremental` -- default is INCREMENTAL
- `test_mode_full` -- FULL mode parsed

### Unit Tests (Plugin)

- `test_multi_source_crawl` -- multiple sources merged
- `test_full_mode_deletes_collection` -- collection deleted before ingest
- `test_incremental_mode_no_delete` -- no delete in INCREMENTAL
- `test_source_config_stored` -- sentinel chunk written
- `test_result_includes_source_results` -- per-source stats in result
- `test_per_source_page_limit` -- event pageLimit overrides config

### Existing Tests

All existing crawler and plugin tests must continue to pass unchanged.

## Rollout Notes

- Backward compatible: existing server code sending `baseUrl`-only events will work without changes
- Server-side can be updated independently to send the new `sources` format
- No database migration needed
- No config changes needed (existing env vars continue to work)
- Feature is additive: no breaking changes to the wire protocol
