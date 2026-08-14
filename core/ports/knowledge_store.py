from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class QueryResult:
    """Result returned from a knowledge store query.

    A distance may be ``None``. Lexical matching answers "does this passage
    contain the term", which has no distance to report — so a passage found
    only that way carries ``None`` rather than a fabricated ``0.0``, which
    would read as a perfect semantic match. Callers must treat ``None`` as
    "no semantic distance available", never as a number.
    """

    documents: list[list[str]]
    metadatas: list[list[dict]]
    distances: list[list[float | None]]
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
        where: dict | None = None,
    ) -> QueryResult:
        """Query similar documents, optionally filtered store-side by metadata.

        ``where=None`` leaves the query unfiltered.  A supplied Chroma ``where``
        predicate is applied before ranking and is used verbatim.
        """
        ...

    async def query_lexical(
        self,
        collection: str,
        terms: list[str],
        n_results: int = 10,
        where: dict | None = None,
    ) -> QueryResult:
        """Find passages containing any of ``terms``, matched literally.

        Complements :meth:`query`, which matches on meaning and can miss an
        exact name or identifier whose surrounding wording is unremarkable.

        Matching is case-insensitive and the terms are literals, not patterns —
        a member's punctuation must never be interpreted. Results carry no
        distance (see :class:`QueryResult`); their order is a ranking, not a
        score, which is why callers fuse by rank rather than by value.

        An empty ``terms`` list yields an empty result without querying.
        """
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
