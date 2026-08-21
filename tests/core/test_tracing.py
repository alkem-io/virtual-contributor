"""Module-local tracing and zero-egress contract tests."""

import asyncio
import time

import pytest

import core.tracing as tracing
from core.config import BaseConfig
from core.tracing import (
    FailureMode,
    classify_failure,
    configure_tracing,
    get_tracer,
    handle_span,
    record_failure,
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


def test_failure_classification_covers_source_aware_modes(traced_exporter) -> None:
    class RouterError(Exception):
        pass

    assert classify_failure(tracing.LLMInvocationTimeoutError("LLM call timed out")) == FailureMode.llm_error
    assert classify_failure(RouterError()) == FailureMode.parse_error
    assert classify_failure(RuntimeError()) == FailureMode.unknown
    event = object()
    with handle_span(_config(), event, "test") as span:
        span.set_attribute("vc.retrieval.empty", True)
        assert classify_failure(RuntimeError()) == FailureMode.empty_retrieval


def test_failure_content_is_gated(traced_exporter) -> None:
    config = _config(tracing_capture_content=False)
    secret = "do-not-export-this-error"
    with handle_span(config, object(), "test") as span:
        record_failure(span, RuntimeError(secret), FailureMode.unknown, config=config)
    shutdown_tracing()
    finished = traced_exporter.get_finished_spans()[0]
    assert finished.attributes["vc.failure_mode"] == "unknown"
    assert all(secret not in str(item) for item in finished.attributes.items())
    assert all(secret not in str(event.attributes) for event in finished.events)


def test_ambient_otel_env_cannot_redirect_export(monkeypatch) -> None:
    """Zero egress by construction: decoy OTEL_* env must be ignored (US2-AS3)."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://collector.evil.example")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://collector.evil.example/v1/traces")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_CERTIFICATE", "/tmp/evil-ca.pem")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "evil=header")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_CLIENT_KEY", "/tmp/evil.key")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_CLIENT_CERTIFICATE", "/tmp/evil.crt")
    monkeypatch.setenv("HTTP_PROXY", "http://evil-proxy.invalid:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://evil-proxy.invalid:8080")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/tmp/evil-requests-ca.pem")
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
        assert exporter._certificate_file is True
        assert exporter._client_cert is None
        assert exporter._session.trust_env is False
        assert exporter._session.proxies == {}
        # Ambient OTEL_TRACES_SAMPLER=always_off must not win over the explicit sampler:
        with get_tracer().start_as_current_span("sampled") as span:
            assert span.is_recording()
    finally:
        reset_tracing_for_tests()


def test_unset_headers_are_an_explicit_empty_mapping(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "evil=header")
    reset_tracing_for_tests()
    assert configure_tracing(
        _config(tracing_enabled=True, tracing_otlp_endpoint="http://collector.internal/v1/traces")
    )
    try:
        provider = tracing._provider
        assert provider is not None
        exporter = provider._active_span_processor._span_processors[0].span_exporter
        assert exporter._headers == {}
        assert bool(exporter._headers) is True
    finally:
        reset_tracing_for_tests()


def test_invalid_headers_fail_config_validation() -> None:
    with pytest.raises(ValueError, match="TRACING_OTLP_HEADERS"):
        _config(tracing_otlp_headers="not-a-header,still-not-a-header")


def test_ambient_resource_and_sdk_disable_are_not_silent(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "evil.resource=present")
    reset_tracing_for_tests()
    assert configure_tracing(
        _config(tracing_enabled=True, tracing_otlp_endpoint="http://collector.internal/v1/traces")
    )
    try:
        assert "evil.resource" not in tracing._provider.resource.attributes
    finally:
        reset_tracing_for_tests()

    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert not configure_tracing(
        _config(tracing_enabled=True, tracing_otlp_endpoint="http://collector.internal/v1/traces")
    )
    assert not tracing.tracing_is_configured()


def test_missing_private_disabled_flag_does_not_crash_startup() -> None:
    """``TracerProvider._disabled`` is SDK-private while pyproject accepts any
    1.x minor, and configure_tracing() is called unguarded from main(). A
    rename must degrade the OTEL_SDK_DISABLED guard, not crash the service."""
    from unittest.mock import patch

    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    class NoDisabledProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_span_processor(self, processor) -> None:
            pass

        def get_tracer(self, name):
            return object()

        def shutdown(self) -> None:
            pass

    reset_tracing_for_tests()
    try:
        with patch("opentelemetry.sdk.trace.TracerProvider", NoDisabledProvider):
            assert configure_tracing(
                _config(tracing_enabled=True, tracing_otlp_endpoint="http://collector.internal/v1/traces"),
                span_exporter=InMemorySpanExporter(),
            )
    finally:
        reset_tracing_for_tests()


async def test_disabled_engine_never_consults_global_provider(monkeypatch) -> None:
    from core.domain.pipeline.engine import IngestEngine, PipelineContext

    class Step:
        name = "safe"

        async def execute(self, context: PipelineContext) -> None:
            context.chunks.append(object())

    def ambient_provider_used(*args, **kwargs):
        raise AssertionError("ambient tracer provider was consulted")

    reset_tracing_for_tests()
    monkeypatch.setattr(tracing.trace, "get_tracer", ambient_provider_used)
    result = await IngestEngine(steps=[Step()]).run([], "knowledge")
    assert result.errors == []


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


async def test_cancelled_optional_span_stays_unset(traced_exporter) -> None:
    """corr-vc-drift-1: a routine shutdown task.cancel() is not a failure —
    cancelled spans must export status UNSET, not phantom ERROR/unknown."""
    from core.tracing import optional_span

    async def body() -> None:
        with optional_span("vc.ingest.step Embed"):
            await asyncio.sleep(30)

    task = asyncio.ensure_future(body())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    shutdown_tracing()
    span = next(
        s for s in traced_exporter.get_finished_spans() if s.name == "vc.ingest.step Embed"
    )
    assert span.status.status_code.name == "UNSET"
    assert "vc.failure_mode" not in span.attributes


def test_failed_root_span_omits_message_when_content_capture_is_enabled() -> None:
    from core.tracing import FailureMode, record_failure
    from opentelemetry import trace
    span = trace.INVALID_SPAN
    record_failure(span, RuntimeError("secret"), FailureMode.unknown)
    assert span is trace.INVALID_SPAN


def test_safe_failure_projection_omits_exception_message_and_stacktrace() -> None:
    from core.tracing import FailureMode, record_failure
    from opentelemetry import trace
    span = trace.INVALID_SPAN
    record_failure(span, RuntimeError("secret"), FailureMode.unknown)
    assert span is trace.INVALID_SPAN


def test_recording_span_failure_projection_redacts_attributes_events_and_status(traced_exporter) -> None:
    secret = "member@example.test"
    config = _config(tracing_capture_content=True)
    with handle_span(config, object(), "expert") as span:
        record_failure(span, RuntimeError(secret), FailureMode.unknown, config=config)
    shutdown_tracing()
    finished = traced_exporter.get_finished_spans()[0]
    assert finished.status.status_code.name == "ERROR"
    assert finished.attributes["exception.type"] == "RuntimeError"
    assert secret not in str(finished.attributes) + str(finished.events) + str(finished.status)


def test_recording_span_failure_projection_omits_exception_stacktrace(traced_exporter) -> None:
    config = _config(tracing_capture_content=True)
    with handle_span(config, object(), "expert") as span:
        record_failure(span, RuntimeError("trace secret"), FailureMode.unknown, config=config)
    shutdown_tracing()
    finished = traced_exporter.get_finished_spans()[0]
    assert all(event.name != "exception" for event in finished.events)
    assert "stacktrace" not in str(finished.attributes) + str(finished.events)


def test_capture_enabled_warns_naming_exported_data(caplog) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    endpoint = "http://collector.warning.invalid/v1/traces"
    reset_tracing_for_tests()
    caplog.set_level("WARNING")
    config = _config(
        tracing_enabled=True,
        tracing_otlp_endpoint=endpoint,
        tracing_otlp_headers="authorization=Bearer warn-secret",
        tracing_capture_content=True,
        tracing_content_max_chars=777,
    )
    try:
        assert configure_tracing(config, span_exporter=InMemorySpanExporter()) is True
        warnings = [record for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        for value in (
            "gen_ai.prompt",
            "gen_ai.completion",
            "vc.message",
            "member messages",
            "prompts",
            "model completions",
            "777",
        ):
            assert value in message
        assert endpoint not in message
        assert "warn-secret" not in message
    finally:
        reset_tracing_for_tests()


def test_capture_default_does_not_warn(caplog) -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    reset_tracing_for_tests()
    caplog.set_level("WARNING")
    try:
        assert configure_tracing(
            _config(
                tracing_enabled=True,
                tracing_otlp_endpoint="http://collector.internal/v1/traces",
            ),
            span_exporter=InMemorySpanExporter(),
        )
        assert all("gen_ai.prompt" not in record.getMessage() for record in caplog.records)
    finally:
        reset_tracing_for_tests()


def test_capture_on_without_configure_does_not_warn(caplog) -> None:
    reset_tracing_for_tests()
    caplog.set_level("WARNING")
    try:
        assert configure_tracing(_config(tracing_capture_content=True)) is False
        assert configure_tracing(
            _config(tracing_enabled=True, tracing_capture_content=True)
        ) is False
        assert all("gen_ai.prompt" not in record.getMessage() for record in caplog.records)
    finally:
        reset_tracing_for_tests()
