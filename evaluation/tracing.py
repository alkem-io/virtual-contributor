"""TracingKnowledgeStore: Decorator wrapper that captures retrieved contexts."""

from __future__ import annotations

from core.ports.knowledge_store import GetResult, KnowledgeStorePort, QueryResult


class TracingKnowledgeStore:
    """Decorator around KnowledgeStorePort that records query results.

    Delegates all calls to the underlying adapter and captures the documents
    returned by query() so they can be extracted for RAGAS evaluation metrics.
    """

    def __init__(self, delegate: KnowledgeStorePort) -> None:
        self._delegate = delegate
        self._captured: list[QueryResult] = []
        self._generation_contexts: list[str] = []

    def capture_generation_context(self, blocks: list[str]) -> None:
        """Capture the exact rendered blocks handed to the answering LLM."""
        self._generation_contexts = list(blocks)

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
        where: dict | None = None,
    ) -> QueryResult:
        result = await self._delegate.query(
            collection, query_texts, n_results, where=where
        )
        self._captured.append(result)
        return result

    async def ingest(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        await self._delegate.ingest(collection, documents, metadatas, ids, embeddings)

    async def delete_collection(self, collection: str) -> None:
        await self._delegate.delete_collection(collection)

    async def query_lexical(
        self,
        collection: str,
        terms: list[str],
        n_results: int = 10,
        where: dict | None = None,
    ) -> QueryResult:
        """Forward lexical retrieval too; hybrid detection is structural."""
        result = await self._delegate.query_lexical(
            collection, terms, n_results, where=where,
        )
        self._captured.append(result)
        return result

    async def get(
        self, collection: str, ids: list[str] | None = None,
        where: dict | None = None, include: list[str] | None = None,
    ) -> GetResult:
        return await self._delegate.get(collection, ids, where, include)

    async def delete(
        self, collection: str, ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        await self._delegate.delete(collection, ids, where)

    def get_retrieved_contexts(self) -> list[str]:
        """Extract all document texts captured during query() calls."""
        contexts: list[str] = []
        for result in self._captured:
            for doc_list in result.documents:
                contexts.extend(doc_list)
        return contexts

    def get_final_detail_contexts(self) -> list[str]:
        """Return only the final store result used for answer detail.

        Hierarchy routing makes an orienting query before detail retrieval.
        RAGAS must score the latter, rather than treating routing overviews as
        generation context.  Flat retrieval naturally has one captured result.
        """

        return list(self._generation_contexts)

    def clear(self) -> None:
        """Reset captured state between test cases."""
        self._captured = []
        self._generation_contexts = []
