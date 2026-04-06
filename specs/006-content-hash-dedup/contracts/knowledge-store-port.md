# Contract: KnowledgeStorePort

**File**: `core/ports/knowledge_store.py`
**Type**: Driven (Secondary) Port — technology-agnostic interface for vector store interactions.

## Current Interface

```python
@runtime_checkable
class KnowledgeStorePort(Protocol):
    async def query(self, collection: str, query_texts: list[str], n_results: int = 10) -> QueryResult: ...
    async def ingest(self, collection: str, documents: list[str], metadatas: list[dict], ids: list[str], embeddings: list[list[float]] | None = None) -> None: ...
    async def delete_collection(self, collection: str) -> None: ...
```

## Extended Interface (this feature)

Two new methods added. Existing methods unchanged.

```python
@dataclass
class GetResult:
    """Result from a get-by-ID or get-by-filter operation."""
    ids: list[str]
    metadatas: list[dict] | None = None
    documents: list[str] | None = None
    embeddings: list[list[float]] | None = None


@runtime_checkable
class KnowledgeStorePort(Protocol):
    # --- Existing (unchanged) ---

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
    ) -> QueryResult: ...

    async def ingest(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> None: ...

    async def delete_collection(self, collection: str) -> None: ...

    # --- New (this feature) ---

    async def get(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> GetResult:
        """Retrieve chunks by ID list and/or metadata filter.

        Args:
            collection: Collection name.
            ids: Optional list of chunk IDs to retrieve.
            where: Optional metadata filter (MongoDB-style syntax, e.g.,
                   {"documentId": "doc-123"}).
            include: Optional list of fields to include in results.
                     Valid values: "metadatas", "documents", "embeddings".
                     If None, returns IDs only.

        Returns:
            GetResult with matching chunks. Empty result if no matches.

        Raises:
            Exception: If the collection does not exist or the store is
                       unreachable.
        """
        ...

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        """Delete chunks by ID list and/or metadata filter.

        At least one of ids or where must be provided.

        Args:
            collection: Collection name.
            ids: Optional list of chunk IDs to delete.
            where: Optional metadata filter for bulk deletion
                   (e.g., {"documentId": "doc-123"}).

        Behavior:
            - Deleting IDs that do not exist completes without error.
            - If the collection does not exist, completes without error.
        """
        ...
```

## Adapter Implementation Notes (ChromaDB)

The `ChromaDBAdapter` implements the new methods using:

```python
# get() → collection.get(ids=ids, where=where, include=include)
# delete() → collection.delete(ids=ids, where=where)
```

Both wrapped in `asyncio.to_thread()` with the existing `_retry()` logic. The `get()` method returns `GetResult` with fields populated based on `include`. The `delete()` method handles "collection not found" gracefully (same pattern as `delete_collection()`).

## Consumers

| Consumer | Method Used | Purpose |
|---|---|---|
| `ChangeDetectionStep` | `get(where={"documentId": doc_id}, include=["metadatas", "embeddings"])` | Look up existing chunks for a document |
| `ChangeDetectionStep` | `get(include=["metadatas"])` | Get all existing document IDs (for removed document detection) |
| `OrphanCleanupStep` | `delete(ids=[...])` | Remove orphaned content chunks |
| `OrphanCleanupStep` | `delete(where={"documentId": doc_id})` | Remove all chunks for a deleted document |

## Backward Compatibility

- Existing `query()`, `ingest()`, and `delete_collection()` methods are unchanged.
- `delete_collection()` is retained but will no longer be called by ingestion plugins (they switch to incremental dedup). It remains available for administrative use.
- The `KnowledgeStorePort` is a Python `Protocol` (structural subtyping). Adding methods means any object previously satisfying the protocol will fail a `runtime_checkable` check unless the new methods are added. Since `ChromaDBAdapter` is the only concrete implementation, the blast radius is contained.
