"""Optional, zero-egress OpenTelemetry tracing for pipeline observability.

The module deliberately owns its provider.  Do not register it globally: doing
so would make unrelated, ambient OpenTelemetry configuration observable by this
service and could route sensitive trace content outside the deployment.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from contextlib import contextmanager
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterator

from opentelemetry import trace

if TYPE_CHECKING:
    from core.config import BaseConfig

logger = logging.getLogger(__name__)

_provider: Any | None = None
_tracer: Any | None = None
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


def _headers(value: str | None) -> dict[str, str] | None:
    if not value:
        return None
    parsed: dict[str, str] = {}
    for item in value.split(","):
        key, separator, header_value = item.partition("=")
        if separator and key.strip():
            parsed[key.strip()] = header_value.strip()
        else:
            logger.warning("Ignoring malformed TRACING_OTLP_HEADERS item")
    return parsed or None


def configure_tracing(
    config: BaseConfig, *, span_exporter: Any | None = None
) -> bool:
    """Configure a process-local OTLP/HTTP provider when explicitly enabled.

    SDK imports live entirely inside this enabled branch.  Constructor arguments
    intentionally supply endpoint, headers and sampler, so no ``OTEL_*``
    environment variable is considered by the exporter or provider.
    """
    global _configured, _provider, _tracer
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

        exporter = OTLPSpanExporter(
            endpoint=config.tracing_otlp_endpoint,
            headers=_headers(config.tracing_otlp_headers),
        )
    else:
        exporter = span_exporter
    service_name = config.tracing_service_name or f"virtual-contributor-{config.plugin_type}"
    resource = Resource.create(
        {
            SERVICE_NAME: service_name,
            SERVICE_VERSION: "0.1.0",
            "vc.plugin": config.plugin_type,
        }
    )
    _provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(TraceIdRatioBased(config.tracing_sample_ratio)),
    )
    _provider.add_span_processor(BatchSpanProcessor(exporter))
    _tracer = _provider.get_tracer("virtual-contributor")
    _configured = True
    return True


def tracing_is_configured() -> bool:
    """Return whether this module owns an active tracing provider."""
    return _configured and _tracer is not None


def get_tracer() -> Any:
    """Return the local tracer or the OpenTelemetry API no-op tracer."""
    return _tracer if _tracer is not None else trace.get_tracer("virtual-contributor")


def shutdown_tracing(timeout_ms: int = 5000) -> None:
    """Flush the bounded batch queue and dispose only our local provider."""
    global _configured, _provider, _tracer
    provider = _provider
    _configured = False
    _provider = None
    _tracer = None
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


def set_content_attribute(span: Any, key: str, text: object, config: BaseConfig) -> None:
    """Set a bounded content attribute only when trace content is allowed."""
    if not config.tracing_capture_content or text is None:
        return
    span.set_attribute(key, str(text)[: config.tracing_content_max_chars])


def classify_failure(exc: BaseException) -> FailureMode:
    """Map operational failures to the fixed dashboard taxonomy."""
    if isinstance(exc, asyncio.TimeoutError):
        return FailureMode.timeout
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return FailureMode.llm_error
    # Router errors intentionally stay duck-typed to avoid a router import here.
    if exc.__class__.__name__ == "RouterError" or isinstance(exc, (ValueError, TypeError)):
        return FailureMode.parse_error
    return FailureMode.unknown


def record_failure(span: Any, exc: BaseException, mode: FailureMode) -> None:
    """Safely record error context and its normalized failure mode."""
    try:
        span.record_exception(exc)
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
        span.set_attribute("vc.failure_mode", mode.value)
    except Exception:
        logger.warning("Unable to record tracing failure", exc_info=True)


@contextmanager
def handle_span(config: BaseConfig, event: object, plugin_name: str) -> Iterator[Any]:
    """Open a root pipeline span and make it available to anomaly helpers."""
    from opentelemetry.trace import SpanKind

    with get_tracer().start_as_current_span("vc.handle", kind=SpanKind.SERVER) as span:
        span.set_attribute("vc.plugin", plugin_name)
        span.set_attribute("vc.event_type", type(event).__name__)
        if hasattr(event, "engine"):
            span.set_attribute("vc.engine", str(getattr(event, "engine")))
            set_content_attribute(span, "vc.message", getattr(event, "message", None), config)
        token = _root_span.set(span)
        try:
            yield span
        finally:
            _root_span.reset(token)


def mark_empty_retrieval() -> None:
    """Flag an empty retrieval on the root trace, including successful runs."""
    span = _root_span.get() or trace.get_current_span()
    try:
        span.set_attribute("vc.retrieval.empty", True)
    except Exception:
        logger.warning("Unable to set empty retrieval indicator", exc_info=True)


def current_root_span() -> Any:
    """Return the local root span, falling back to the current API span."""
    return _root_span.get() or trace.get_current_span()
