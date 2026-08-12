"""Knowledge-store decorator which adds non-invasive retrieval spans."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from core.ports.knowledge_store import GetResult, KnowledgeStorePort, QueryResult
from core.tracing import get_tracer


class TracedKnowledgeStore:
    """Delegate every KnowledgeStorePort operation while recording its outcome."""

    def __init__(self, delegate: KnowledgeStorePort) -> None:
        self._delegate = delegate

    @staticmethod
    def _query_attributes(span: Any, collection: str, n_results: int, result: QueryResult) -> None:
        returned = len(result.documents[0]) if result.documents else 0
        span.set_attribute("vc.retrieval.collection", collection)
        span.set_attribute("vc.retrieval.n_requested", n_results)
        span.set_attribute("vc.retrieval.n_returned", returned)
        distances = result.distances[0] if result.distances else []
        if distances:
            scores = [1.0 - distance for distance in distances]
            span.set_attribute("vc.retrieval.score_max", max(scores))
            span.set_attribute("vc.retrieval.score_min", min(scores))
            span.set_attribute("vc.retrieval.score_mean", sum(scores) / len(scores))

    async def query(self, collection: str, query_texts: list[str], n_results: int = 10) -> QueryResult:
        current = trace.get_current_span()
        if getattr(current, "name", None) == "vc.retrieval":
            result = await self._delegate.query(collection, query_texts, n_results)
            self._query_attributes(current, collection, n_results, result)
            return result
        with get_tracer().start_as_current_span("vc.retrieval", kind=SpanKind.CLIENT) as span:
            try:
                result = await self._delegate.query(collection, query_texts, n_results)
                self._query_attributes(span, collection, n_results, result)
                return result
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                raise

    async def ingest(self, collection: str, documents: list[str], metadatas: list[dict], ids: list[str], embeddings: list[list[float]] | None = None) -> None:
        await self._operation("ingest", collection, len(documents), self._delegate.ingest(collection, documents, metadatas, ids, embeddings))

    async def delete_collection(self, collection: str) -> None:
        await self._operation("delete_collection", collection, None, self._delegate.delete_collection(collection))

    async def get(self, collection: str, ids: list[str] | None = None, where: dict | None = None, include: list[str] | None = None) -> GetResult:
        return await self._operation("get", collection, len(ids) if ids else None, self._delegate.get(collection, ids, where, include))

    async def delete(self, collection: str, ids: list[str] | None = None, where: dict | None = None) -> None:
        await self._operation("delete", collection, len(ids) if ids else None, self._delegate.delete(collection, ids, where))

    async def _operation(self, operation: str, collection: str, count: int | None, awaitable: Any) -> Any:
        with get_tracer().start_as_current_span(f"vc.store.{operation}", kind=SpanKind.CLIENT) as span:
            span.set_attribute("vc.retrieval.collection", collection)
            if count is not None:
                span.set_attribute("vc.store.n_items", count)
            try:
                return await awaitable
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                raise
