"""Module-local tracing and zero-egress contract tests."""

import asyncio
import time

import core.tracing as tracing
from core.config import BaseConfig
from core.tracing import (
    FailureMode,
    classify_failure,
    configure_tracing,
    get_tracer,
    reset_tracing_for_tests,
    set_content_attribute,
    shutdown_tracing,
)


def _config(**values) -> BaseConfig:
    return BaseConfig(llm_base_url="http://local-model", **values)


def test_disabled_is_noop() -> None:
    reset_tracing_for_tests()
    assert configure_tracing(_config()) is False
    with get_tracer().start_as_current_span("no-op") as span:
        assert not span.is_recording()


def test_in_memory_exporter_receives_span(traced_exporter) -> None:
    with get_tracer().start_as_current_span("recorded") as span:
        span.set_attribute("number", 1)
    shutdown_tracing()
    assert [span.name for span in traced_exporter.get_finished_spans()] == ["recorded"]


def test_enabled_without_endpoint_warns(caplog) -> None:
    assert configure_tracing(_config(tracing_enabled=True)) is False
    assert "TRACING_OTLP_ENDPOINT" in caplog.text


def test_content_attributes_are_gated_and_bounded(traced_exporter) -> None:
    config = _config(tracing_capture_content=True, tracing_content_max_chars=3)
    with get_tracer().start_as_current_span("content") as span:
        set_content_attribute(span, "content", "abcdef", config)
        span.set_attribute("numeric", 2)
    shutdown_tracing()
    attributes = traced_exporter.get_finished_spans()[0].attributes
    assert attributes["content"] == "abc"
    assert attributes["numeric"] == 2


def test_failure_classification() -> None:
    assert classify_failure(asyncio.TimeoutError()) == FailureMode.timeout
    assert classify_failure(ConnectionError()) == FailureMode.llm_error
    assert classify_failure(ValueError()) == FailureMode.parse_error


def test_ambient_otel_env_cannot_redirect_export(monkeypatch) -> None:
    """Zero egress by construction: decoy OTEL_* env must be ignored (US2-AS3)."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.evil.example")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://collector.evil.example/v1/traces")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    reset_tracing_for_tests()
    config = _config(
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal:4318/v1/traces",
        tracing_otlp_headers="authorization=Bearer secret-token",
    )
    assert configure_tracing(config) is True
    try:
        provider = tracing._provider
        assert provider is not None
        processor = provider._active_span_processor._span_processors[0]
        exporter = processor.span_exporter
        assert exporter._endpoint == "http://collector.internal:4318/v1/traces"
        assert exporter._headers == {"authorization": "Bearer secret-token"}
        # Ambient OTEL_TRACES_SAMPLER=always_off must not win over the explicit sampler:
        with get_tracer().start_as_current_span("sampled") as span:
            assert span.is_recording()
    finally:
        reset_tracing_for_tests()


def test_backend_absent_never_blocks_or_raises() -> None:
    """Unroutable endpoint + real batch processor: spans drop off-path (US2-AS2)."""
    reset_tracing_for_tests()
    config = _config(
        tracing_enabled=True,
        tracing_otlp_endpoint="http://127.0.0.1:1/v1/traces",
    )
    assert configure_tracing(config) is True
    try:
        started = time.monotonic()
        for i in range(50):
            with get_tracer().start_as_current_span(f"hot-path-{i}") as span:
                span.set_attribute("i", i)
        elapsed = time.monotonic() - started
        # Export happens on the batch worker thread; the hot path never waits on it.
        assert elapsed < 1.0
    finally:
        # Flush toward the dead endpoint must fail quietly, never raise.
        shutdown_tracing(timeout_ms=500)
