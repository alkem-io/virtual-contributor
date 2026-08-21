"""Optional, explicitly configured OpenTelemetry tracing for observability.

The module deliberately owns its provider.  Do not register it globally: doing
so would make unrelated, ambient OpenTelemetry configuration observable by this
service and could route sensitive trace content outside the deployment.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from contextlib import contextmanager, nullcontext
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Iterator

from opentelemetry import trace

if TYPE_CHECKING:
    from core.config import BaseConfig

logger = logging.getLogger(__name__)

_provider: Any | None = None
_tracer: trace.Tracer | None = None
_active_config: BaseConfig | None = None
_configured = False
_root_span: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "vc_tracing_root_span", default=None
)


class FailureMode(str, Enum):
    timeout = "timeout"
    llm_error = "llm_error"
    empty_retrieval = "empty_retrieval"
    parse_error = "parse_error"
    unknown = "unknown"


class _ExplicitHeaders(dict[str, str]):
    """An empty but truthy mapping, preventing the exporter env fallback."""

    def __bool__(self) -> bool:
        return True


class _ExplicitUnset(str):
    """A truthy empty string for SDK constructors which use ``value or env``."""

    def __new__(cls) -> _ExplicitUnset:
        return super().__new__(cls, "")

    def __bool__(self) -> bool:
        return True


def _headers(value: str | None) -> dict[str, str]:
    """Parse service-owned headers without accepting SDK environment values."""
    if not value:
        return _ExplicitHeaders()
    parsed: dict[str, str] = {}
    for item in value.split(","):
        key, separator, header_value = item.partition("=")
        if separator and key.strip():
            parsed[key.strip()] = header_value.strip()
        else:
            logger.warning("Ignoring malformed TRACING_OTLP_HEADERS item")
    return _ExplicitHeaders(parsed)


def _service_version() -> str:
    """Return installed package metadata, retaining source-tree compatibility."""
    try:
        return version("alkemio-virtual-contributor")
    except PackageNotFoundError:
        return "0.1.0"


def configure_tracing(
    config: BaseConfig, *, span_exporter: Any | None = None
) -> bool:
    """Configure a process-local OTLP/HTTP provider when explicitly enabled.

    SDK imports live entirely inside this enabled branch. Constructor arguments
    intentionally supply every export setting, so ambient ``OTEL_*`` settings
    cannot select an endpoint, transport, headers, sampler, or batch limits.
    """
    global _active_config, _configured, _provider, _tracer
    if not config.tracing_enabled:
        return False
    if not config.tracing_otlp_endpoint:
        logger.warning("Tracing is enabled but TRACING_OTLP_ENDPOINT is not configured; tracing stays off")
        return False

    # Keep imports lazy: disabled service instances never exercise SDK code.
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    if _provider is not None:
        shutdown_tracing()
    if span_exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        import requests
        from opentelemetry.exporter.otlp.proto.http import Compression

        session = requests.Session()
        session.trust_env = False
        session.proxies = {}
        # OTLPSpanExporter adds its protocol headers after construction; this
        # clears inherited Requests defaults and leaves configured headers in
        # sole control of this process.
        session.headers.clear()
        exporter = OTLPSpanExporter(
            endpoint=config.tracing_otlp_endpoint,
            headers=_headers(config.tracing_otlp_headers),
            certificate_file=True,
            client_key_file=_ExplicitUnset(),
            client_certificate_file=_ExplicitUnset(),
            timeout=5,
            compression=Compression.NoCompression,
            session=session,
        )
        # The truthy explicit sentinels above prevent the HTTP exporter's
        # ``x or environ[...]`` fallback. Clear the temporary values before
        # any request can be made so no client certificate is configured.
        exporter._client_key_file = None  # type: ignore[attr-defined]
        exporter._client_certificate_file = None  # type: ignore[attr-defined]
        exporter._client_cert = None  # type: ignore[attr-defined]
    else:
        exporter = span_exporter
    service_name = config.tracing_service_name or f"virtual-contributor-{config.plugin_type}"
    resource = Resource(
        attributes={
            SERVICE_NAME: service_name,
            SERVICE_VERSION: _service_version(),
            "vc.plugin": config.plugin_type,
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(config.tracing_sample_ratio)),
        # This module owns the provider lifecycle (shutdown_tracing on a
        # bounded daemon thread). The SDK's atexit hook would re-run the
        # blocking flush after main() returns, unbounding process exit
        # against a dead collector (measured 35s > k8s 30s grace period).
        shutdown_on_exit=False,
    )
    # Read defensively: ``_disabled`` is SDK-private. configure_tracing() is
    # called unguarded from main(), so a rename in an accepted 1.x minor would
    # turn an observability detail into a startup crash. Absent flag => not
    # disabled, which is the fail-open behaviour the rest of this module uses.
    if getattr(provider, "_disabled", False):
        logger.warning("Tracing is disabled by OTEL_SDK_DISABLED; tracing stays off")
        provider.shutdown()
        return False
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            schedule_delay_millis=1000,
            max_export_batch_size=512,
            export_timeout_millis=5000,
        )
    )
    _provider = provider
    _tracer = provider.get_tracer("virtual-contributor")
    _active_config = config
    _configured = True
    if config.tracing_capture_content:
        logger.warning(
            "Tracing content capture is enabled: member messages, prompts, and model completions "
            "will be exported to the trace collector as span attributes gen_ai.prompt, "
            "gen_ai.completion, and vc.message, each truncated to %s characters.",
            config.tracing_content_max_chars,
        )
    return True


def tracing_is_configured() -> bool:
    """Return whether this module owns an active tracing provider."""
    return _configured and _tracer is not None


def get_tracer() -> trace.Tracer:
    """Return the local tracer or an explicit no-op tracer.

    Deliberately do not call ``trace.get_tracer`` here: that could pick up an
    application-wide provider installed by a dependency while tracing is off.
    """
    return _tracer if _tracer is not None else trace.NoOpTracer()


def shutdown_tracing(timeout_ms: int = 5000) -> None:
    """Flush the bounded batch queue and dispose only our local provider."""
    global _active_config, _configured, _provider, _tracer
    provider = _provider
    _configured = False
    _provider = None
    _tracer = None
    _active_config = None
    if provider is None:
        return
    try:
        provider.force_flush(timeout_millis=timeout_ms)
        provider.shutdown()
    except Exception:
        logger.warning("Unable to flush tracing provider during shutdown", exc_info=True)


def reset_tracing_for_tests() -> None:
    """Reset module state without modifying the global OpenTelemetry provider."""
    shutdown_tracing()
    _root_span.set(None)


def set_content_attribute(span: trace.Span, key: str, text: object, config: BaseConfig) -> None:
    """Set a bounded content attribute only when trace content is allowed."""
    if not config.tracing_capture_content or text is None:
        return
    span.set_attribute(key, str(text)[: config.tracing_content_max_chars])


class LLMInvocationError(ConnectionError):
    """An LLM-adapter failure. Subclasses ConnectionError so pre-existing
    callers catching the adapter's historical exception type keep working."""


class LLMInvocationTimeoutError(LLMInvocationError, TimeoutError):
    """A timeout whose source is a provider call rather than the root pipeline."""


def mark_llm_failure(exc: BaseException) -> BaseException:
    """Tag an exception as LLM-sourced without changing its type."""
    try:
        exc.__vc_llm_error__ = True  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - exotic immutable exceptions
        pass
    return exc


def classify_failure(exc: BaseException) -> FailureMode:
    """Map operational failures to the fixed dashboard taxonomy."""
    if isinstance(exc, LLMInvocationError) or getattr(exc, "__vc_llm_error__", False):
        return FailureMode.llm_error
    if isinstance(exc, asyncio.TimeoutError):
        return FailureMode.timeout
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return FailureMode.llm_error
    # Router errors intentionally stay duck-typed to avoid a router import here.
    if exc.__class__.__name__ == "RouterError" or isinstance(exc, (ValueError, TypeError)):
        return FailureMode.parse_error
    root = _root_span.get()
    if root is not None and getattr(root, "attributes", {}).get("vc.retrieval.empty"):
        return FailureMode.empty_retrieval
    return FailureMode.unknown


def record_failure(
    span: trace.Span, exc: BaseException, mode: FailureMode, *, config: BaseConfig | None = None
) -> None:
    """Safely record error context and its normalized failure mode."""
    try:
        # Exception text may contain request data, predicates, provider URLs or
        # credentials. Preserve the object for internal control flow, but never
        # project its text or traceback into telemetry.
        span.set_status(trace.Status(trace.StatusCode.ERROR))
        span.set_attribute("exception.type", type(exc).__name__)
        span.set_attribute("vc.failure_mode", mode.value)
    except Exception:
        logger.warning("Unable to record tracing failure", exc_info=True)


@contextmanager
def optional_span(
    name: str, *, kind: trace.SpanKind = trace.SpanKind.INTERNAL
) -> Iterator[trace.Span | None]:
    """Open an instrumentation span only for this module's configured provider.

    SDK auto-recording is disabled so exception content stays gated behind
    ``tracing_capture_content`` — ``record_failure`` is the single writer of
    error context, invoked here so a raising body still exports status ERROR
    (span-schema contract) without leaking the exception message.
    """
    if not tracing_is_configured():
        with nullcontext(None) as span:
            yield span
        return
    with get_tracer().start_as_current_span(
        name, kind=kind, record_exception=False, set_status_on_exception=False
    ) as span:
        try:
            yield span
        except Exception as exc:
            # Exception, not BaseException: a CancelledError from a routine
            # shutdown task.cancel() is not a failure (FR-007) — recording it
            # would flood the SC-006 error rate with phantom `unknown`s.
            record_failure(span, exc, classify_failure(exc))
            raise


@contextmanager
def handle_span(config: BaseConfig, event: object, plugin_name: str) -> Iterator[trace.Span]:
    """Open a root pipeline span and make it available to anomaly helpers."""
    from opentelemetry.trace import SpanKind

    with get_tracer().start_as_current_span(
        "vc.handle",
        kind=SpanKind.SERVER,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("vc.plugin", plugin_name)
        span.set_attribute("vc.event_type", type(event).__name__)
        if hasattr(event, "engine"):
            span.set_attribute("vc.engine", str(getattr(event, "engine")))
        token = _root_span.set(span)
        try:
            yield span
        finally:
            _root_span.reset(token)


def mark_empty_retrieval() -> None:
    """Flag an empty retrieval on the root trace, including successful runs."""
    span = current_root_span()
    try:
        span.set_attribute("vc.retrieval.empty", True)
    except Exception:
        logger.warning("Unable to set empty retrieval indicator", exc_info=True)


def current_root_span() -> trace.Span:
    """Return the local root span, never an ambient provider's current span."""
    return _root_span.get() or trace.INVALID_SPAN
