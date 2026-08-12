"""Knowledge store tracing decorator tests."""

import pytest

from core.ports.knowledge_store import KnowledgeStorePort, QueryResult
from core.tracing import shutdown_tracing
from core.tracing_knowledge_store import TracedKnowledgeStore
from tests.conftest import MockKnowledgeStorePort


async def test_traced_store_delegates_and_adds_retrieval_statistics(traced_exporter) -> None:
    store = TracedKnowledgeStore(MockKnowledgeStorePort())
    assert isinstance(store, KnowledgeStorePort)
    await store.query("knowledge", ["question"], 2)
    shutdown_tracing()
    span = traced_exporter.get_finished_spans()[0]
    assert span.name == "vc.retrieval"
    assert span.attributes["vc.retrieval.n_returned"] == 2
    assert span.attributes["vc.retrieval.score_max"] == pytest.approx(0.9)


async def test_store_exceptions_are_preserved(traced_exporter) -> None:
    class FailingStore(MockKnowledgeStorePort):
        async def query(self, collection: str, query_texts: list[str], n_results: int = 10) -> QueryResult:
            raise RuntimeError("store unavailable")

    with pytest.raises(RuntimeError, match="store unavailable"):
        await TracedKnowledgeStore(FailingStore()).query("knowledge", ["question"])
