"""Default-off and explicit-on tracing content contracts."""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from core.config import BaseConfig
from core.tracing import (
    FailureMode,
    handle_span,
    record_failure,
    set_content_attribute,
    shutdown_tracing,
)
from core.tracing_callbacks import VCTracingCallbackHandler


CONTENT_KEYS = ("gen_ai.prompt", "gen_ai.completion", "vc.message")


def _config(**values: object) -> BaseConfig:
    return BaseConfig(
        llm_base_url="http://local-model",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
        **values,
    )


def _complete_chat(
    config: BaseConfig,
    *,
    prompt: str = "member prompt sentinel",
    completion: object = "model completion sentinel",
    request_model: str = "request-model",
    model: str = "response-model",
) -> None:
    handler = VCTracingCallbackHandler(config)
    run_id = uuid4()
    handler.on_chat_model_start(
        {"name": request_model},
        [[HumanMessage(content=prompt)]],
        run_id=run_id,
    )
    message = (
        AIMessage(
            content=completion,
            usage_metadata={"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        )
        if isinstance(completion, str)
        else SimpleNamespace(
            content=completion,
            usage_metadata={"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        )
    )
    response = SimpleNamespace(
        generations=[[
            SimpleNamespace(message=message)
        ]],
        llm_output={"model_name": model},
    )
    handler.on_llm_end(response, run_id=run_id)


def _assert_no_content(spans: list[Any], *sentinels: str) -> None:
    for span in spans:
        attributes = span.attributes
        assert all(key not in attributes for key in CONTENT_KEYS)
        rendered = str((attributes, span.events, span.status))
        assert all(sentinel not in rendered for sentinel in sentinels)


def test_default_config_exports_no_content_anywhere(traced_exporter) -> None:
    config = _config()
    prompt = "member prompt sentinel"
    completion = "model completion sentinel"
    message = "member text sentinel"

    _complete_chat(config, prompt=prompt, completion=completion)
    with handle_span(config, object(), "test") as span:
        set_content_attribute(span, "vc.message", message, config)
    shutdown_tracing()

    spans = list(traced_exporter.get_finished_spans())
    assert spans
    _assert_no_content(spans, message, prompt, completion)


async def test_default_wiring_end_to_end_root_span_dark(traced_exporter) -> None:
    from core.events.response import Response
    from tests.core.test_main_tracing import _Message, _query_body, _wiring

    async def handle(event):
        return Response(result="answer")

    handler, _, config, _ = _wiring(handle)
    assert config.tracing_capture_content is False
    await handler(_query_body(), _Message())
    shutdown_tracing()

    root = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle")
    assert root.status.status_code.name == "OK"
    assert "vc.message" not in root.attributes


async def test_default_early_ack_success_span_omits_future_message_content(
    traced_exporter, monkeypatch,
) -> None:
    import asyncio

    from core.events.ingest_website import IngestWebsite, IngestWebsiteResult
    from tests.core.test_main_tracing import _Message, _wiring

    class MessageBearingIngestWebsite(IngestWebsite):
        message: str

    event = MessageBearingIngestWebsite(
        baseUrl="https://example.test",
        type="website",
        purpose="knowledge",
        personaId="persona",
        message="future early-ACK member message",
    )

    async def handle(_event):
        return IngestWebsiteResult()

    monkeypatch.setattr(
        "core.router.Router.parse_event", lambda _router, _body: event,
    )
    handler, active, config, _ = _wiring(handle, plugin_type="ingest-website")
    assert config.tracing_capture_content is False
    message = _Message()
    await handler({"eventType": "IngestWebsite"}, message)
    await asyncio.gather(*active)
    shutdown_tracing()

    spans = list(traced_exporter.get_finished_spans())
    assert message.acked
    assert any(span.name == "vc.handle" and span.status.status_code.name == "OK" for span in spans)
    assert all("vc.message" not in span.attributes for span in spans)


async def test_capture_enabled_early_ack_success_records_bounded_future_message(
    traced_exporter, monkeypatch,
) -> None:
    import asyncio

    from core.events.ingest_website import IngestWebsite, IngestWebsiteResult
    from tests.core.test_main_tracing import _Message, _wiring

    class MessageBearingIngestWebsite(IngestWebsite):
        message: str

    event = MessageBearingIngestWebsite(
        baseUrl="https://example.test",
        type="website",
        purpose="knowledge",
        personaId="persona",
        message="future early-ACK member message",
    )

    async def handle(_event):
        return IngestWebsiteResult()

    monkeypatch.setattr(
        "core.router.Router.parse_event", lambda _router, _body: event,
    )
    handler, active, _, _ = _wiring(
        handle,
        plugin_type="ingest-website",
        tracing_capture_content=True,
        tracing_content_max_chars=7,
    )
    await handler({"eventType": "IngestWebsite"}, _Message())
    await asyncio.gather(*active)
    shutdown_tracing()

    root = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle")
    assert root.status.status_code.name == "OK"
    assert root.attributes["vc.message"] == "future "


def test_default_config_keeps_noncontent_diagnostics(traced_exporter) -> None:
    _complete_chat(_config())
    shutdown_tracing()

    span = traced_exporter.get_finished_spans()[0]
    assert span.attributes["gen_ai.usage.input_tokens"] == 3
    assert span.attributes["gen_ai.usage.output_tokens"] == 5
    assert span.attributes["gen_ai.request.model"] == "request-model"
    assert span.attributes["gen_ai.response.model"] == "response-model"
    assert span.end_time is not None


def test_default_config_failure_diagnostics_intact(traced_exporter) -> None:
    config = _config()
    with handle_span(config, object(), "test") as span:
        record_failure(span, RuntimeError("pii-sentinel"), FailureMode.unknown, config=config)
    shutdown_tracing()

    spans = list(traced_exporter.get_finished_spans())
    root = next(span for span in spans if span.name == "vc.handle")
    assert root.status.status_code.name == "ERROR"
    assert root.attributes["exception.type"] == "RuntimeError"
    assert root.attributes["vc.failure_mode"] == "unknown"
    _assert_no_content(spans, "pii-sentinel")


def test_explicit_on_behaviour_unchanged(traced_exporter) -> None:
    config = _config(tracing_capture_content=True, tracing_content_max_chars=5)
    _complete_chat(config, prompt="prompt text", completion="completion text")
    _complete_chat(
        config,
        prompt="none prompt",
        completion=None,
        request_model="none-request-model",
        model="none-model",
    )
    with handle_span(config, object(), "test") as span:
        set_content_attribute(span, "vc.message", "member message", config)
    shutdown_tracing()

    spans = list(traced_exporter.get_finished_spans())
    chat = next(span for span in spans if span.name == "chat request-model")
    none_completion = next(span for span in spans if span.name == "chat none-request-model")
    root = next(span for span in spans if span.name == "vc.handle")
    assert chat.attributes["gen_ai.prompt"] == "promp"
    assert chat.attributes["gen_ai.completion"] == "compl"
    assert root.attributes["vc.message"] == "membe"
    assert "gen_ai.completion" not in none_completion.attributes
