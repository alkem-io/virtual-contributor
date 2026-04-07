"""TracingKnowledgeStore: Decorator wrapper that captures retrieved contexts."""

from __future__ import annotations

from core.ports.knowledge_store import KnowledgeStorePort, QueryResult


class TracingKnowledgeStore:
    """Decorator around KnowledgeStorePort that records query results.

    Delegates all calls to the underlying adapter and captures the documents
    returned by query() so they can be extracted for RAGAS evaluation metrics.
    """

    def __init__(self, delegate: KnowledgeStorePort) -> None:
        self._delegate = delegate
        self._captured: list[QueryResult] = []

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
    ) -> QueryResult:
        result = await self._delegate.query(collection, query_texts, n_results)
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

    def get_retrieved_contexts(self) -> list[str]:
        """Extract all document texts captured during query() calls."""
        contexts: list[str] = []
        for result in self._captured:
            for doc_list in result.documents:
                contexts.extend(doc_list)
        return contexts

    def clear(self) -> None:
        """Reset captured state between test cases."""
        self._captured = []
