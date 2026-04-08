# Tasks: First-class Website Ingestion API (VC Service Side)

**Story:** alkem-io/alkemio#1828
**Date:** 2026-04-08

---

## Task Dependency Order

```
T1 (event models) --> T3 (crawler) --> T5 (plugin)
T2 (port+adapter) --> T5 (plugin)
T3 (crawler) --> T4 (crawler tests)
T1 (event models) --> T4 (crawler tests)
T5 (plugin) --> T6 (plugin tests)
T2 (port+adapter) --> T6 (plugin tests)
```

T1 and T2 are independent. T3 depends on T1. T4 depends on T1+T3. T5 depends on T1+T2+T3. T6 depends on all.

---

## T1: Extend IngestWebsite event models

**File:** `core/events/ingest_website.py`

**Acceptance criteria:**
- WebsiteSource model with url, pageLimit, maxDepth, includePatterns, excludePatterns fields (camelCase aliases)
- IngestionMode enum with FULL and INCREMENTAL values
- IngestWebsite model extended with optional `sources` list and `mode` field (default INCREMENTAL)
- Backward compat: `base_url` becomes optional; model_validator synthesizes single-element sources list from baseUrl when sources is absent
- IngestWebsiteProgress model with sourceUrl, status, pagesCrawled, chunksProcessed
- Existing fields (type, purpose, persona_id, summarization_model) remain unchanged

**Tests that prove it done:**
- test_event_sources_deserialization: parse JSON with sources array
- test_event_mode_deserialization: parse JSON with mode=FULL
- test_event_backward_compat_base_url: parse legacy JSON with only baseUrl
- test_default_page_limit_and_depth: verify WebsiteSource defaults

---

## T2: Add collection metadata methods to KnowledgeStorePort and adapters

**Files:** `core/ports/knowledge_store.py`, `core/adapters/chromadb.py`, `tests/conftest.py`

**Acceptance criteria:**
- KnowledgeStorePort protocol gains get_collection_metadata(collection) -> dict and set_collection_metadata(collection, metadata) -> None
- ChromaDBAdapter implements both using ChromaDB's collection.modify() and collection.metadata
- MockKnowledgeStorePort in tests/conftest.py implements both with in-memory dict storage

**Tests that prove it done:**
- test_source_config_stored_in_metadata (in T6): verifies end-to-end metadata persistence via mock

---

## T3: Enhance crawler with maxDepth and pattern filtering

**File:** `plugins/ingest_website/crawler.py`

**Acceptance criteria:**
- crawl() accepts max_depth parameter (default -1 = unlimited, 0 = base only, N = N hops)
- crawl() accepts include_patterns: list[str] | None (glob patterns matched against URL path)
- crawl() accepts exclude_patterns: list[str] | None (glob patterns matched against URL path)
- Depth tracking: each URL in the queue has an associated depth; links from depth D pages are at depth D+1
- Pattern matching uses fnmatch against URL path component
- Existing behavior unchanged when new params are absent/default

**Tests that prove it done:**
- test_crawl_max_depth_zero: only base page crawled
- test_crawl_max_depth_one: base page + direct links
- test_crawl_include_patterns: only matching paths crawled
- test_crawl_exclude_patterns: matching paths skipped

---

## T4: Crawler unit tests

**File:** `tests/plugins/test_ingest_website.py`

**Acceptance criteria:**
- All new crawler tests pass
- All existing crawler tests still pass unchanged

**Tests that prove it done:**
- TestCrawlFunction class extended with depth and pattern tests

---

## T5: Rewrite plugin for multi-source, mode, and metadata persistence

**File:** `plugins/ingest_website/plugin.py`

**Acceptance criteria:**
- Resolves effective sources from event (backward compat: baseUrl -> single source)
- Collection naming: uses persona_id when sources provided, falls back to legacy netloc for baseUrl-only
- FULL mode: calls delete_collection() before ingesting
- INCREMENTAL mode (default): no delete, uses existing change-detection pipeline
- Iterates over each source, calls crawl() with source-specific params
- Aggregates all documents across sources
- After successful ingest, stores source config JSON in collection metadata via set_collection_metadata
- Returns IngestWebsiteResult with aggregated success/failure
- Individual source failures do not abort remaining sources

**Tests that prove it done:**
- test_full_mode_deletes_collection
- test_incremental_mode_no_delete
- test_multi_source_ingestion
- test_source_config_stored_in_metadata
- test_backward_compat_base_url_collection_naming

---

## T6: Plugin and integration tests

**File:** `tests/plugins/test_ingest_website.py`

**Acceptance criteria:**
- All new plugin tests pass
- All existing plugin tests still pass unchanged
- make_ingest_website factory in conftest.py supports new fields

**Tests that prove it done:**
- Full test suite green: `poetry run pytest tests/plugins/test_ingest_website.py`

---

## T7: Static analysis and final gate

**Acceptance criteria:**
- `poetry run ruff check core/ plugins/ tests/` passes
- `poetry run pyright core/ plugins/` passes
- `poetry run pytest` (full suite) passes
- No regressions in any existing test

**Tests that prove it done:**
- All three commands exit 0
