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
        async def query(self, collection: str, query_texts: list[str], n_results: int = 10, where: dict | None = None) -> QueryResult:
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


async def test_reused_retrieval_span_records_failure_exactly_once(
    traced_exporter, traced_config
) -> None:
    """In the real wiring the plugin's ``optional_span('vc.retrieval')`` already
    owns the span and records the failure as it propagates. The reused-span
    branch must therefore NOT record again: a second record_failure would emit
    a duplicate exception event on one span and double-count the error rate."""
    class FailingStore(MockKnowledgeStorePort):
        async def query(self, collection: str, query_texts: list[str], n_results: int = 10, where: dict | None = None) -> QueryResult:
            raise RuntimeError("store unavailable")

    event = make_input(bodyOfKnowledgeID="bok")
    with handle_span(traced_config, event, "expert"):
        try:
            await ExpertPlugin(MockLLMPort(), TracedKnowledgeStore(FailingStore())).handle(event)
        except Exception:
            pass
    shutdown_tracing()
    retrieval = [s for s in traced_exporter.get_finished_spans() if s.name == "vc.retrieval"]
    assert retrieval, "no retrieval span was exported"
    for span in retrieval:
        assert span.status.status_code.name == "ERROR"
        assert len([e for e in span.events if e.name == "exception"]) == 1


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
        async def query(self, collection, query_texts, n_results=10, where=None):
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


async def test_the_tracing_wrapper_forwards_the_metadata_filter() -> None:
    """The wrapper is transparent by contract.

    Dropping `where` here would silently disable scoped retrieval for every
    caller that goes through tracing — no error, just quietly unfiltered
    results. This surfaced when #107 (metadata filter) and #108 (tracing) were
    merged: the wrapper predated the kwarg and swallowed it.
    """
    seen: dict = {}

    class _Recording:
        async def query(self, collection, query_texts, n_results=10, where=None):
            seen["where"] = where
            return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])

    store = TracedKnowledgeStore(_Recording())
    sentinel = {"embeddingType": {"$ne": "summary"}}
    await store.query("c", ["q"], 5, sentinel)
    assert seen["where"] == sentinel, "the tracing wrapper dropped the filter"


async def test_lexical_none_distances_do_not_crash_the_span_stats() -> None:
    """A literally-matched passage has distance None (#114); `1.0 - None`
    raised TypeError inside the span writer, failing the very retrieval the
    wrapper exists to observe."""

    class _MixedStore:
        async def query(self, collection, query_texts, n_results=10, where=None):
            return QueryResult(
                documents=[["semantic hit", "literal hit"]],
                metadatas=[[{}, {}]],
                distances=[[0.2, None]],
                ids=[["a", "b"]],
            )

    store = TracedKnowledgeStore(_MixedStore())
    result = await store.query("c", ["q"], 5)
    assert result.documents == [["semantic hit", "literal hit"]]
