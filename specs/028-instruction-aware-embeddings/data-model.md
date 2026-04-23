# Data Model: Instruction-Aware Embeddings

**Branch**: `028-instruction-aware-embeddings` | **Date**: 2026-04-23

---

## Summary

No new Pydantic models, database schemas, or event types are introduced. The changes are limited to a new method on the `EmbeddingsPort` protocol, a new config field, and constructor/protocol changes in adapter code.

---

## Protocol Change: EmbeddingsPort

```python
# Before
@runtime_checkable
class EmbeddingsPort(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        ...

# After
@runtime_checkable
class EmbeddingsPort(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for documents (indexing side)."""
        ...

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for retrieval queries.

        Instruction-aware models prepend a task-specific prefix on the
        query side. Adapters for plain models implement this as an alias
        for embed().
        """
        ...
```

- **New method**: `embed_query(texts)` -- semantically distinct from `embed()`.
- **Impact**: All implementations of `EmbeddingsPort` must add `embed_query()`. Three implementations updated: `OpenAICompatibleEmbeddingsAdapter`, `OpenAIEmbeddingsAdapter`, `MockEmbeddingsPort`.

---

## Constructor Change: OpenAICompatibleEmbeddingsAdapter

```python
# Before
def __init__(self, api_key: str, endpoint: str, model_name: str) -> None:

# After
def __init__(
    self,
    api_key: str,
    endpoint: str,
    model_name: str,
    query_instruction: str | None = None,  # NEW
) -> None:
```

- **`query_instruction`** (`str | None`, default `None`): Explicit instruction prefix for query-side wrapping. When `None`, auto-detection applies based on model name. When set (including empty string), used verbatim.
- Stored after resolution as `self._query_instruction: str` via `_resolve_query_instruction()`.

---

## New Module-Level Constant

Added to `core/adapters/openai_compatible_embeddings.py`:

| Constant | Value |
|----------|-------|
| `QWEN3_RETRIEVAL_INSTRUCTION` | `"Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "` |

---

## Config Field Change: BaseConfig

```python
# Before
embeddings_api_key: str | None = None
embeddings_endpoint: str | None = None
embeddings_model_name: str | None = None

# After
embeddings_api_key: str | None = None
embeddings_endpoint: str | None = None
embeddings_model_name: str | None = None
embeddings_query_instruction: str | None = None  # NEW
```

- **`embeddings_query_instruction`** (`str | None`, default `None`): Maps to `EMBEDDINGS_QUERY_INSTRUCTION` env var. Passed to `OpenAICompatibleEmbeddingsAdapter` constructor.

---

## ChromaDB Internal Protocol Change

```python
# Before (in chromadb.py)
class EmbedFn(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

# After
class EmbedFn(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, texts: list[str]) -> list[list[float]]: ...
```

- `ChromaDBAdapter.query()` now calls `self._embeddings.embed_query(query_texts)` instead of `self._embeddings.embed(query_texts)`.

---

## Mock Port Change: MockEmbeddingsPort

```python
# Before
class MockEmbeddingsPort:
    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1] * self.dimension for _ in texts]

# After
class MockEmbeddingsPort:
    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []
        self.query_calls: list[list[str]] = []  # NEW

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1] * self.dimension for _ in texts]

    async def embed_query(self, texts: list[str]) -> list[list[float]]:  # NEW
        self.query_calls.append(texts)
        return [[0.1] * self.dimension for _ in texts]
```

- Separate `query_calls` tracker enables tests to assert that retrieval paths call `embed_query()` while ingest paths call `embed()`.

---

## Unchanged

- `LLMPort` protocol -- no changes
- `KnowledgeStorePort` protocol -- no changes (ChromaDB adapter is the consumer)
- Event models (`Input`, `IngestWebsite`, `IngestBodyOfKnowledge`) -- no changes
- Pipeline models (`Document`, `Chunk`, `DocumentMetadata`, `IngestResult`) -- no changes
- Plugin constructors -- no changes
