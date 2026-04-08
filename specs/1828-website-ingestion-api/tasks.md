# Tasks: First-class Website Ingestion API (VC Service Side)

**Story:** alkem-io/alkemio#1828
**Date:** 2026-04-08

## Task List (dependency-ordered)

### T1: Extend `IngestWebsite` event schema

**File:** `core/events/ingest_website.py`
**Depends on:** None
**Description:**
- Add `IngestionMode` enum (FULL, INCREMENTAL)
- Add `WebsiteSource` model with fields: url, pageLimit, maxDepth, includePatterns, excludePatterns
- Add `SourceResult` model with fields: url, pagesProcessed, error
- Modify `IngestWebsite`: make `base_url` optional, add `sources` list, add `mode` field
- Add `model_validator` to synthesize `sources` from `base_url` when `sources` is empty
- Make `type`, `purpose` fields have defaults for backward compat
- Extend `IngestWebsiteResult`: add `source_results` list
- Update `core/events/__init__.py` to re-export new types

**Acceptance criteria:**
- Old wire format `{"baseUrl": "...", "type": "...", "purpose": "...", "personaId": "..."}` still validates
- New wire format with `sources` array validates
- `mode` defaults to INCREMENTAL
- `source_results` serializes with camelCase alias

**Tests:**
- `test_backward_compat_base_url_only`
- `test_new_format_with_sources`
- `test_mode_default_incremental`
- `test_mode_full`
- `test_source_result_serialization`

---

### T2: Add maxDepth support to crawler

**File:** `plugins/ingest_website/crawler.py`
**Depends on:** None (parallel with T1)
**Description:**
- Change BFS queue from `list[str]` to `list[tuple[str, int]]` to track depth
- Add `max_depth` parameter to `crawl()` (default -1 for unlimited)
- Only enqueue discovered links when `depth + 1 <= max_depth` (or max_depth == -1)
- Base URL starts at depth 0

**Acceptance criteria:**
- `max_depth=0` returns only the base page
- `max_depth=1` returns base + direct links, does not follow links from depth-1 pages
- `max_depth=-1` (default) follows all links (backward compat)

**Tests:**
- `test_max_depth_zero_base_only`
- `test_max_depth_one`
- `test_max_depth_unlimited_default`

---

### T3: Add URL pattern filtering to crawler

**File:** `plugins/ingest_website/crawler.py`
**Depends on:** None (parallel with T1, T2)
**Description:**
- Add `include_patterns` and `exclude_patterns` parameters to `crawl()`
- Add helper `_matches_patterns(url, patterns)` using `fnmatch.fnmatch` on URL path
- In the crawl loop, before adding a discovered URL to the queue:
  - If `exclude_patterns` is set and URL path matches any, skip
  - If `include_patterns` is set and URL path does not match any, skip
- Base URL is always crawled regardless of patterns

**Acceptance criteria:**
- Include patterns filter discovered links to only matching paths
- Exclude patterns skip matching discovered links
- Exclude takes precedence over include
- Base URL is always crawled even with restrictive patterns
- No patterns (None/empty) = crawl everything (backward compat)

**Tests:**
- `test_include_patterns_filter`
- `test_exclude_patterns_filter`
- `test_exclude_overrides_include`
- `test_base_url_always_crawled_with_include`
- `test_no_patterns_crawls_all`

---

### T4: Update plugin for multi-source and mode support

**File:** `plugins/ingest_website/plugin.py`
**Depends on:** T1, T2, T3
**Description:**
- Iterate over `event.sources`, crawling each source sequentially
- Pass source-level `page_limit`, `max_depth`, `include_patterns`, `exclude_patterns` to `crawl()`
- Fall back `page_limit` to `IngestWebsiteConfig.process_pages_limit` when None
- Merge all documents from all sources before running the pipeline
- Use `{personaId}-knowledge` as collection name
- If `event.mode == FULL`, call `delete_collection()` before pipeline
- Track per-source stats and build `SourceResult` list
- Store source config as sentinel chunk `__source_config__` via `ingest()` port with `embeddingType=config` to avoid interference with ChangeDetection/OrphanCleanup (which filter on `embeddingType=chunk`)
- Return `IngestWebsiteResult` with `source_results`

**Acceptance criteria:**
- Multiple sources crawled and documents merged
- FULL mode deletes collection first
- INCREMENTAL mode does not delete collection
- Per-source stats in result
- Source config sentinel stored
- Legacy events (baseUrl only) still work end-to-end

**Tests:**
- `test_multi_source_crawl`
- `test_full_mode_deletes_collection`
- `test_incremental_mode_no_delete`
- `test_source_config_stored`
- `test_result_includes_source_results`
- `test_per_source_page_limit_fallback`
- `test_legacy_event_still_works`

---

### T5: Update test fixtures and factories

**File:** `tests/conftest.py`
**Depends on:** T1
**Description:**
- Update `make_ingest_website()` to support both old and new formats
- Add `make_website_source()` helper for building `WebsiteSource` objects
- Ensure existing tests still pass with updated factory

**Acceptance criteria:**
- `make_ingest_website()` works with no args (backward compat)
- `make_ingest_website(sources=[...])` works with new format
- All existing tests pass unchanged

**Tests:**
- Existing test suite passes

---

### T6: Comprehensive integration tests

**File:** `tests/plugins/test_ingest_website.py`
**Depends on:** T1, T2, T3, T4, T5
**Description:**
- Add tests for all new crawler behaviors (depth, patterns)
- Add tests for plugin multi-source, mode, metadata, result reporting
- Add event model tests for backward compat and new format
- Verify all existing tests still pass

**Acceptance criteria:**
- Full test coverage of new functionality
- No regressions in existing tests
- All tests pass with `poetry run pytest`

---

### T7: Static analysis and final verification

**Depends on:** T1-T6
**Description:**
- Run `poetry run ruff check core/ plugins/ tests/`
- Run `poetry run pyright core/ plugins/`
- Fix any issues found
- Run full test suite one final time

**Acceptance criteria:**
- Zero ruff violations
- Zero pyright errors
- All tests pass
