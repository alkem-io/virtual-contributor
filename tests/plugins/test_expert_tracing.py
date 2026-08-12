"""Expert retrieval quality tracing coverage."""

from core.tracing import handle_span, shutdown_tracing
from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


async def test_expert_retrieval_has_post_filter_counts(traced_exporter) -> None:
    event = make_input(bodyOfKnowledgeId="bok")
    config = type("C", (), {"tracing_capture_content": True, "tracing_content_max_chars": 100})()
    with handle_span(config, event, "expert"):
        await ExpertPlugin(MockLLMPort(), MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    retrieval = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.retrieval")
    assert retrieval.attributes["vc.retrieval.chunks_passed"] == 2
