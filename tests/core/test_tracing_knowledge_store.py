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


async def test_store_failure_content_is_gated(traced_exporter, monkeypatch) -> None:
    """SEC-4 regression: with content capture OFF, a raising delegate must not
    export the exception message/stacktrace through the store spans."""
    from core.config import BaseConfig
    from core.tracing import configure_tracing, reset_tracing_for_tests, shutdown_tracing
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    reset_tracing_for_tests()
    exporter = InMemorySpanExporter()
    config = BaseConfig(
        llm_base_url="http://local-model",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
        tracing_capture_content=False,
    )
    configure_tracing(config, span_exporter=exporter)
    secret = "confidential-document-uri-must-not-export"

    class RaisingStore:
        async def query(self, collection, query_texts, n_results=10):
            raise RuntimeError(secret)

        async def ingest(self, collection, documents, metadatas, ids, embeddings=None):
            raise RuntimeError(secret)

        async def get(self, collection, ids=None, where=None, include=None):
            raise RuntimeError(secret)

        async def delete(self, collection, ids=None, where=None):
            raise RuntimeError(secret)

        async def delete_collection(self, collection):
            raise RuntimeError(secret)

    store = TracedKnowledgeStore(RaisingStore())
    for op in (
        store.query("c", ["q"]),
        store.ingest("c", ["d"], [{}], ["i"]),
        store.delete_collection("c"),
    ):
        try:
            await op
        except RuntimeError:
            pass
    try:
        shutdown_tracing()
        for span in exporter.get_finished_spans():
            assert all(secret not in str(item) for item in span.attributes.items()), span.name
            for event in span.events:
                assert secret not in str(event.attributes), span.name
            assert secret not in str(span.status.description or ""), span.name
    finally:
        reset_tracing_for_tests()
