"""Guidance tracing coverage."""

from core.tracing import handle_span, shutdown_tracing
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


async def test_guidance_retrievals_are_spanned(traced_exporter) -> None:
    event = make_input()
    config = type("C", (), {"tracing_capture_content": True, "tracing_content_max_chars": 100})()
    with handle_span(config, event, "guidance"):
        await GuidancePlugin(MockLLMPort(), MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    assert [span.name for span in traced_exporter.get_finished_spans()].count("vc.retrieval") == 3
