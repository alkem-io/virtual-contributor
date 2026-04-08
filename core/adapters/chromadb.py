from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

import chromadb

from core.ports.knowledge_store import GetResult, QueryResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


class EmbedFn(Protocol):
    """Minimal protocol for an async embed function."""
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ChromaDBAdapter:
    """ChromaDB knowledge store adapter behind KnowledgeStorePort."""

    def __init__(
        self,
        host: str,
        port: int = 8765,
        credentials: str | None = None,
        embeddings: EmbedFn | None = None,
        distance_fn: str = "cosine",
    ) -> None:
        settings = chromadb.config.Settings()
        if credentials:
            settings = chromadb.config.Settings(
                chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
                chroma_client_auth_credentials=credentials,
            )
        self._client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=settings,
        )
        self._embeddings = embeddings
        self._distance_fn = distance_fn

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
    ) -> QueryResult:
        if self._embeddings is None:
            raise ValueError(
                "ChromaDBAdapter requires an embeddings provider when "
                "embedding_function=None"
            )
        query_embeddings = await self._embeddings.embed(query_texts)

        def _query():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            results = col.query(
                query_embeddings=query_embeddings, n_results=n_results
            )
            return QueryResult(
                documents=results.get("documents", []),
                metadatas=results.get("metadatas", []),
                distances=results.get("distances", []),
                ids=results.get("ids", []),
            )

        return await self._retry(_query)

    async def ingest(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        if embeddings is None:
            raise ValueError(
                "Precomputed embeddings are required when embedding_function=None"
            )

        def _ingest():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            col.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
                embeddings=embeddings,
            )

        await self._retry(_ingest)

    async def delete_collection(self, collection: str) -> None:
        def _delete():
            try:
                self._client.delete_collection(collection)
            except Exception as exc:
                msg = str(exc).lower()
                if "not found" in msg or "does not exist" in msg:
                    logger.warning("Collection %s not found for deletion, skipping", collection)
                    return
                raise

        await self._retry(_delete)

    async def get(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> GetResult:
        def _get():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            kwargs: dict = {}
            if ids is not None:
                kwargs["ids"] = ids
            if where is not None:
                kwargs["where"] = where
            if include is not None:
                kwargs["include"] = include
            result = col.get(**kwargs)
            return GetResult(
                ids=result.get("ids", []),
                metadatas=result.get("metadatas"),
                documents=result.get("documents"),
                embeddings=result.get("embeddings"),
            )

        return await self._retry(_get)

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        def _delete_items():
            try:
                col = self._client.get_or_create_collection(
                    collection,
                    embedding_function=None,
                    metadata={"hnsw:space": self._distance_fn},
                )
                kwargs: dict = {}
                if ids is not None:
                    kwargs["ids"] = ids
                if where is not None:
                    kwargs["where"] = where
                col.delete(**kwargs)
            except Exception as exc:
                msg = str(exc).lower()
                if "not found" in msg or "does not exist" in msg:
                    return
                raise

        await self._retry(_delete_items)

    @staticmethod
    async def _retry(fn, max_retries: int = MAX_RETRIES) -> Any:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(fn)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning("ChromaDB attempt %d failed, retrying: %s", attempt + 1, exc)
                    await asyncio.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Retry called with max_retries=0")

    @staticmethod
    def combine_query_results(*results: QueryResult) -> QueryResult:
        """Merge multiple query results into one."""
        combined = QueryResult(documents=[], metadatas=[], distances=[], ids=[])
        for r in results:
            combined.documents.extend(r.documents)
            combined.metadatas.extend(r.metadatas)
            combined.distances.extend(r.distances)
            combined.ids.extend(r.ids)
        return combined
