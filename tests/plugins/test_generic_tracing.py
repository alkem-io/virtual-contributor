"""Generic history-condensation tracing coverage."""

from core.tracing import handle_span, shutdown_tracing
from plugins.generic.plugin import GenericPlugin
from tests.conftest import MockLLMPort, make_input


async def test_history_condensation_has_stage_span(traced_exporter) -> None:
    event = make_input(history=[{"role": "human", "content": "Earlier"}])
    with handle_span(type("C", (), {"tracing_capture_content": True, "tracing_content_max_chars": 100})(), event, "generic"):
        await GenericPlugin(MockLLMPort()).handle(event)
    shutdown_tracing()
    assert "vc.stage query_processing" in [span.name for span in traced_exporter.get_finished_spans()]
