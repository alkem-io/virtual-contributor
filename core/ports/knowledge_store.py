from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class QueryResult:
    """Result returned from a knowledge store query."""

    documents: list[list[str]]
    metadatas: list[list[dict]]
    distances: list[list[float]]
    ids: list[list[str]]


@dataclass
class GetResult:
    """Result from a get-by-ID or get-by-filter operation."""

    ids: list[str]
    metadatas: list[dict] | None = None
    documents: list[str] | None = None
    embeddings: list[list[float]] | None = None


@runtime_checkable
class KnowledgeStorePort(Protocol):
    """Port for vector knowledge store interactions."""

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
    ) -> QueryResult:
        """Query a collection for similar documents."""
        ...

    async def ingest(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        """Ingest documents into a collection."""
        ...

    async def delete_collection(self, collection: str) -> None:
        """Delete an entire collection."""
        ...

    async def get(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> GetResult:
        """Retrieve chunks by ID list and/or metadata filter."""
        ...

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        """Delete chunks by ID list and/or metadata filter."""
        ...

    async def get_collection_metadata(
        self, collection: str
    ) -> dict[str, Any]:
        """Read collection-level metadata (not chunk metadata)."""
        ...

    async def set_collection_metadata(
        self, collection: str, metadata: dict[str, Any]
    ) -> None:
        """Write collection-level metadata (merges with existing)."""
        ...
