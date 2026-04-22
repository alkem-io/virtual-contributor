# Data Model: Map-Reduce Summarization

**Branch**: `027-map-reduce-summarization` | **Date**: 2026-04-22

---

## Summary

No new Pydantic models, database schemas, or event types are introduced. The changes are limited to constructor signature extensions on two existing classes and new module-level prompt constants.

---

## Constructor Signature Changes

### `DocumentSummaryStep.__init__`

```python
# Before
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,
    embed_batch_size: int = 50,
) -> None:

# After
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    concurrency: int = 8,
    chunk_threshold: int = 4,
    embeddings_port: EmbeddingsPort | None = None,
    embed_batch_size: int = 50,
    reduce_llm_port: LLMPort | None = None,        # NEW
) -> None:
```

- **`reduce_llm_port`** (`LLMPort | None`, default `None`): Optional LLM port for the reduce phase of map-reduce summarization. When `None`, falls back to `llm_port`. Intended for a higher-quality model that handles cross-chunk synthesis.
- Stored as `self._reduce_llm = reduce_llm_port or llm_port`.

### `BodyOfKnowledgeSummaryStep.__init__`

```python
# Before
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    max_section_chars: int = 30000,
    knowledge_store_port: KnowledgeStorePort | None = None,
    embeddings_port: EmbeddingsPort | None = None,
) -> None:

# After
def __init__(
    self,
    llm_port: LLMPort,
    summary_length: int = 10000,
    max_section_chars: int = 30000,
    knowledge_store_port: KnowledgeStorePort | None = None,
    embeddings_port: EmbeddingsPort | None = None,
    map_llm_port: LLMPort | None = None,            # NEW
) -> None:
```

- **`map_llm_port`** (`LLMPort | None`, default `None`): Optional LLM port for the map phase of map-reduce summarization. When `None`, falls back to `llm_port`. Intended for a cheaper/faster model that handles individual section summarization.
- Stored as `self._map_llm = map_llm_port or llm_port`.

---

## New Prompt Constants

Added to `core/domain/pipeline/prompts.py` as module-level string constants:

| Constant | Purpose |
|----------|---------|
| `DOCUMENT_MAP_TEMPLATE` | User prompt for per-chunk document summarization (map phase) |
| `DOCUMENT_REDUCE_SYSTEM` | System prompt for merging partial document summaries (reduce phase) |
| `DOCUMENT_REDUCE_TEMPLATE` | User prompt for merging partial document summaries (reduce phase) |
| `BOK_MAP_TEMPLATE` | User prompt for per-section BoK extraction (map phase) |
| `BOK_REDUCE_SYSTEM` | System prompt for merging partial BoK overviews (reduce phase) |
| `BOK_REDUCE_TEMPLATE` | User prompt for merging partial BoK overviews (reduce phase) |

All prompts use `{budget}` and `{text}` or `{summaries}` format placeholders, consistent with the existing refine prompts.

---

## Internal Function Signature

The new `_map_reduce_summarize` function is a module-level async helper (not a class method):

```python
async def _map_reduce_summarize(
    chunks: list[str],
    *,
    map_invoke,           # Callable[[list[dict]], Awaitable[str]]
    reduce_invoke,        # Callable[[list[dict]], Awaitable[str]]
    max_length: int,
    map_system: str,
    map_template: str,
    reduce_system: str,
    reduce_template: str,
    concurrency: int = 5,
    reduce_fanin: int = 6,
) -> str:
```

This is not part of the public data model but is documented here for completeness since it defines the map-reduce algorithm's interface.

---

## Unchanged

- `PipelineContext` dataclass -- no new fields
- `Chunk`, `Document`, `DocumentMetadata` models -- no changes
- `IngestResult` model -- no changes
- `LLMPort` protocol -- no changes
- Event models (`IngestBodyOfKnowledge`, `IngestWebsite`) -- no changes
