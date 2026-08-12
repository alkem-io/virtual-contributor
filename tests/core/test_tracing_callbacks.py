"""LangChain callback span contract tests."""

from types import SimpleNamespace
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from core.config import BaseConfig
from core.tracing import get_tracer, shutdown_tracing
from core.tracing_callbacks import VCTracingCallbackHandler


def _config() -> BaseConfig:
    return BaseConfig(llm_base_url="http://local-model", tracing_enabled=True, tracing_otlp_endpoint="http://internal")


def test_callback_lifecycle_and_usage(traced_exporter) -> None:
    handler = VCTracingCallbackHandler(_config())
    run_id = uuid4()
    handler.on_chat_model_start({"name": "test-model"}, [[HumanMessage(content="prompt")]], run_id=run_id)
    response = SimpleNamespace(
        generations=[[SimpleNamespace(message=AIMessage(content="answer", usage_metadata={"input_tokens": 3, "output_tokens": 5, "total_tokens": 8}))]],
        llm_output={"model_name": "response-model"},
    )
    handler.on_llm_end(response, run_id=run_id)
    shutdown_tracing()
    span = traced_exporter.get_finished_spans()[0]
    assert span.name == "chat test-model"
    assert span.attributes["gen_ai.usage.input_tokens"] == 3
    assert span.attributes["gen_ai.usage.output_tokens"] == 5


def test_callback_errors_do_not_escape(traced_exporter) -> None:
    handler = VCTracingCallbackHandler(_config())
    run_id = uuid4()
    handler.on_chat_model_start({"name": "model"}, [[]], run_id=run_id)
    original = get_tracer

    def fail_start(*args, **kwargs):
        raise RuntimeError("instrumentation failure")

    # Start has already created the real span; an internal handler failure must
    # remain fail-open rather than escaping into the provider call.
    import core.tracing_callbacks as callbacks

    callbacks.get_tracer = fail_start
    try:
        handler.on_chat_model_start({"name": "second"}, [[]], run_id=uuid4())
        handler.on_llm_end(object(), run_id=run_id)
    finally:
        callbacks.get_tracer = original


def test_non_numeric_usage_still_ends_span(traced_exporter) -> None:
    handler = VCTracingCallbackHandler(_config())
    run_id = uuid4()
    handler.on_chat_model_start({"name": "model"}, [[HumanMessage(content="prompt")]], run_id=run_id)
    response = SimpleNamespace(
        generations=[[SimpleNamespace(message=AIMessage(content="answer"))]],
        llm_output={"token_usage": {"prompt_tokens": "n/a"}},
    )
    handler.on_llm_end(response, run_id=run_id)
    shutdown_tracing()
    span = traced_exporter.get_finished_spans()[0]
    assert span.name == "chat model"
    assert "gen_ai.usage.input_tokens" not in span.attributes


def test_run_ids_are_isolated(traced_exporter) -> None:
    handler = VCTracingCallbackHandler(_config())
    first, second = uuid4(), uuid4()
    handler.on_chat_model_start({"name": "first"}, [[]], run_id=first)
    handler.on_chat_model_start({"name": "second"}, [[]], run_id=second)
    handler.on_llm_end(SimpleNamespace(generations=[]), run_id=second)
    handler.on_llm_end(SimpleNamespace(generations=[]), run_id=first)
    shutdown_tracing()
    assert {span.name for span in traced_exporter.get_finished_spans()} == {"chat first", "chat second"}
