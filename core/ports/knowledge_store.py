from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class QueryResult:
    """Result returned from a knowledge store query."""

    documents: list[list[str]]
    metadatas: list[list[dict]]
    distances: list[list[float]]
    ids: list[list[str]]


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
    ) -> None:
        """Ingest documents into a collection."""
        ...

    async def delete_collection(self, collection: str) -> None:
        """Delete an entire collection."""
        ...
