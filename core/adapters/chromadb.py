from __future__ import annotations

import asyncio
import logging
from typing import Any

import chromadb

from core.ports.knowledge_store import QueryResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


class ChromaDBAdapter:
    """ChromaDB knowledge store adapter behind KnowledgeStorePort."""

    def __init__(self, host: str, port: int = 8765, credentials: str | None = None) -> None:
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

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
    ) -> QueryResult:
        def _query():
            col = self._client.get_or_create_collection(collection)
            results = col.query(query_texts=query_texts, n_results=n_results)
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
    ) -> None:
        def _ingest():
            col = self._client.get_or_create_collection(collection)
            col.upsert(documents=documents, metadatas=metadatas, ids=ids)

        await self._retry(_ingest)

    async def delete_collection(self, collection: str) -> None:
        def _delete():
            self._client.delete_collection(collection)

        try:
            await asyncio.to_thread(_delete)
        except Exception:
            logger.warning("Collection %s not found for deletion", collection)

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
