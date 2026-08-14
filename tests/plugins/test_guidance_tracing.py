"""Guidance tracing coverage."""

from core.tracing import handle_span, shutdown_tracing
from core.ports.knowledge_store import QueryResult
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


async def test_guidance_retrievals_are_spanned(traced_exporter, traced_config) -> None:
    event = make_input()
    with handle_span(traced_config, event, "guidance"):
        await GuidancePlugin(MockLLMPort(), MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    assert [span.name for span in traced_exporter.get_finished_spans()].count("vc.retrieval") == 3


async def test_guidance_empty_flag_is_based_on_merged_results(traced_exporter, traced_config) -> None:
    class PartlyEmptyStore(MockKnowledgeStorePort):
        async def query(self, collection, query_texts, n_results=10, where=None):
            if collection == "alkem.io-knowledge":
                return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])
            return await super().query(collection, query_texts, n_results)

    event = make_input()
    with handle_span(traced_config, event, "guidance"):
        await GuidancePlugin(MockLLMPort(), PartlyEmptyStore()).handle(event)
    shutdown_tracing()
    root = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle")
    assert "vc.retrieval.empty" not in root.attributes
    assert root.attributes["vc.retrieval.chunks_passed"] == 1


async def test_guidance_all_empty_marks_root_and_parse_fallback(traced_exporter, traced_config) -> None:
    class EmptyStore(MockKnowledgeStorePort):
        async def query(self, collection, query_texts, n_results=10, where=None):
            return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])

    event = make_input()
    with handle_span(traced_config, event, "guidance"):
        response = await GuidancePlugin(MockLLMPort("plain response"), EmptyStore()).handle(event)
    shutdown_tracing()
    root = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle")
    assert response.result == "plain response"
    assert root.attributes["vc.retrieval.empty"] is True
    assert root.events[-1].name == "vc.parse_fallback"


async def test_failed_collection_is_recorded_once(traced_exporter, traced_config) -> None:
    class FailingStore(MockKnowledgeStorePort):
        async def query(self, collection, query_texts, n_results=10, where=None):
            if collection == "alkem.io-knowledge":
                raise RuntimeError("collection failed")
            return await super().query(collection, query_texts, n_results)

    event = make_input()
    with handle_span(traced_config, event, "guidance"):
        await GuidancePlugin(MockLLMPort(), FailingStore()).handle(event)
    shutdown_tracing()
    failed = next(
        span for span in traced_exporter.get_finished_spans()
        if span.name == "vc.retrieval" and span.status.status_code.name == "ERROR"
    )
    assert failed.status.status_code.name == "ERROR"
    assert len([event for event in failed.events if event.name == "exception"]) == 1
