# Plan: First-class Website Ingestion API (VC Service Side)

**Story:** alkem-io/alkemio#1828
**Date:** 2026-04-08

---

## 1. Architecture

The changes follow the existing Microkernel + Hexagonal architecture. No new plugins are created; the existing `ingest_website` plugin is enhanced. Changes span four layers:

1. **Events layer** (`core/events/ingest_website.py`) -- Extended Pydantic models for the enriched message format
2. **Ports layer** (`core/ports/knowledge_store.py`) -- New collection metadata methods on KnowledgeStorePort
3. **Adapters layer** (`core/adapters/chromadb.py`) -- ChromaDB implementation of collection metadata operations
4. **Plugin layer** (`plugins/ingest_website/`) -- Crawler enhancements, multi-source orchestration, progress reporting

### Data Flow (Enhanced)

```
RabbitMQ (enriched IngestWebsite msg)
  --> Router.parse_event()
    --> IngestWebsite model (with sources[], mode)
      --> IngestWebsitePlugin.handle()
        --> for each source:
              crawl(url, page_limit, max_depth, include_patterns, exclude_patterns)
              --> Documents
        --> if mode == FULL: delete_collection()
        --> IngestEngine.run(all_documents, collection_name)
        --> store source config in collection metadata
        --> emit IngestWebsiteResult
```

## 2. Affected Modules

| Module | Change Type | Description |
|--------|------------|-------------|
| `core/events/ingest_website.py` | **Modify** | Add WebsiteSource, IngestionMode models; extend IngestWebsite with sources/mode fields; add backward compat validator; add IngestWebsiteProgress model |
| `core/ports/knowledge_store.py` | **Modify** | Add get_collection_metadata() and set_collection_metadata() protocol methods |
| `core/adapters/chromadb.py` | **Modify** | Implement collection metadata methods using ChromaDB's collection.modify() API |
| `plugins/ingest_website/crawler.py` | **Modify** | Add max_depth and include/exclude pattern parameters to crawl() |
| `plugins/ingest_website/plugin.py` | **Modify** | Multi-source orchestration, FULL/INCREMENTAL mode, source config persistence, collection naming |
| `tests/conftest.py` | **Modify** | Update MockKnowledgeStorePort with collection metadata methods; update make_ingest_website factory |
| `tests/plugins/test_ingest_website.py` | **Modify** | Add tests for all new acceptance criteria |

## 3. Data Model Deltas

### New Event Models (core/events/ingest_website.py)

```python
class WebsiteSource(BaseModel):
    url: str
    page_limit: int = Field(default=20, alias="pageLimit")
    max_depth: int = Field(default=-1, alias="maxDepth")
    include_patterns: list[str] | None = Field(default=None, alias="includePatterns")
    exclude_patterns: list[str] | None = Field(default=None, alias="excludePatterns")

class IngestionMode(str, Enum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"

class IngestWebsite(EventBase):  # MODIFIED
    # Existing fields preserved for backward compat
    base_url: str | None = Field(default=None, alias="baseUrl")
    type: str = ""
    purpose: str = ""
    persona_id: str = Field(default="", alias="personaId")
    summarization_model: str = Field(default="mistral-medium", alias="summarizationModel")
    # New fields
    sources: list[WebsiteSource] | None = None
    mode: IngestionMode = Field(default=IngestionMode.INCREMENTAL)
    # Validator: if sources absent but baseUrl present, synthesize single source

class IngestWebsiteProgress(EventBase):
    source_url: str = Field(alias="sourceUrl")
    status: str  # CRAWLING, SUMMARIZING, EMBEDDING, STORING, COMPLETED, FAILED
    pages_crawled: int = Field(default=0, alias="pagesCrawled")
    chunks_processed: int = Field(default=0, alias="chunksProcessed")
```

### Port Extension (core/ports/knowledge_store.py)

```python
# New methods on KnowledgeStorePort Protocol:
async def get_collection_metadata(self, collection: str) -> dict[str, Any]: ...
async def set_collection_metadata(self, collection: str, metadata: dict[str, Any]) -> None: ...
```

### Collection Metadata Schema

```json
{
  "_source_config": "[{\"url\": \"...\", \"pageLimit\": 20, ...}]",
  "_ingestion_mode": "INCREMENTAL",
  "_last_ingested_at": "2026-04-08T12:00:00Z"
}
```

## 4. Interface Contracts

### crawl() -- Enhanced Signature

```python
async def crawl(
    base_url: str,
    page_limit: int = 20,
    max_depth: int = -1,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[dict]:
```

### IngestWebsitePlugin.handle() -- Unchanged Signature

The handle method signature stays `handle(event: IngestWebsite, **ports)`. Internally it now:
1. Resolves sources from event (backward compat normalization)
2. Determines collection name from persona_id or legacy netloc
3. Optionally wipes collection (FULL mode)
4. Crawls each source with its parameters
5. Runs ingest pipeline on aggregated documents
6. Stores source config in collection metadata
7. Returns IngestWebsiteResult

## 5. Test Strategy

### Unit Tests (tests/plugins/test_ingest_website.py)

| Test | Covers AC |
|------|-----------|
| test_event_sources_deserialization | AC1 |
| test_event_mode_deserialization | AC2 |
| test_event_backward_compat_base_url | AC3 |
| test_crawl_max_depth_zero | AC4 |
| test_crawl_max_depth_one | AC4 |
| test_crawl_include_patterns | AC5 |
| test_crawl_exclude_patterns | AC6 |
| test_full_mode_deletes_collection | AC7 |
| test_incremental_mode_no_delete | AC8 |
| test_multi_source_ingestion | AC9 |
| test_source_config_stored_in_metadata | AC10 |
| test_default_page_limit_and_depth | AC12 |

### Existing Tests -- Must Continue Passing

All existing tests in `tests/plugins/test_ingest_website.py` must pass unchanged (backward compat).

## 6. Rollout Notes

- **Backward compatible**: Old-format messages (with baseUrl only) continue to work via the model_validator.
- **No migration needed**: Collection metadata is written on next ingest; absent metadata on existing collections is handled gracefully.
- **No new dependencies**: All implementation uses stdlib (fnmatch) and existing deps (pydantic, httpx, bs4, chromadb).
- **Feature flag**: None needed -- new fields are optional with sensible defaults matching current behavior.
