"""Knowledge store tracing decorator tests."""

import pytest

from core.ports.knowledge_store import KnowledgeStorePort, QueryResult
from core.tracing import handle_span, shutdown_tracing
from core.tracing_knowledge_store import TracedKnowledgeStore
from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


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


async def test_plugin_and_store_merge_retrieval_attributes_on_one_span(
    traced_exporter, traced_config
) -> None:
    event = make_input(bodyOfKnowledgeID="bok")
    with handle_span(traced_config, event, "expert"):
        await ExpertPlugin(
            MockLLMPort(), TracedKnowledgeStore(MockKnowledgeStorePort())
        ).handle(event)
    shutdown_tracing()
    spans = [span for span in traced_exporter.get_finished_spans() if span.name == "vc.retrieval"]
    assert len(spans) == 1
    attributes = spans[0].attributes
    assert attributes["vc.retrieval.n_returned"] == 2
    assert attributes["vc.retrieval.score_max"] == pytest.approx(0.9)
    assert attributes["vc.retrieval.chunks_passed"] == 2


async def test_store_operation_span_is_emitted(traced_exporter) -> None:
    store = TracedKnowledgeStore(MockKnowledgeStorePort())
    await store.ingest("knowledge", ["doc"], [{}], ["id"])
    shutdown_tracing()
    span = traced_exporter.get_finished_spans()[0]
    assert span.name == "vc.store.ingest"
    assert span.attributes["vc.store.n_items"] == 1
