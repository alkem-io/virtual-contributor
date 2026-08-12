"""Main composition seams and startup logging tracing regression coverage."""

from unittest.mock import MagicMock, patch

from core.config import BaseConfig
from core.tracing import configure_tracing, reset_tracing_for_tests, shutdown_tracing
from main import _log_config, _mask_sensitive, _shutdown_tracing_bounded


def test_tracing_config_logging_is_safe(caplog) -> None:
    _log_config(BaseConfig(llm_base_url="http://local", tracing_otlp_headers="Authorization=secret"))
    assert "Authorization=secret" not in caplog.text


def test_url_userinfo_is_masked() -> None:
    assert _mask_sensitive("llm_base_url", "https://user:secret@llm.internal/v1") == "https://***@llm.internal/v1"
    assert _mask_sensitive("tracing_otlp_endpoint", "https://token@collector.internal/v1/traces") == "https://***@collector.internal/v1/traces"


def test_factory_adds_callbacks_only_after_local_tracing_is_configured() -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from core.provider_factory import create_llm_adapter

    config = BaseConfig(
        llm_base_url="http://local",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
    )
    model = MagicMock()
    with patch("core.provider_factory._get_model_class", return_value=MagicMock(return_value=model)) as factory:
        reset_tracing_for_tests()
        create_llm_adapter(config)
        assert "callbacks" not in factory.return_value.call_args.kwargs
        configure_tracing(config, span_exporter=InMemorySpanExporter())
        create_llm_adapter(config)
        assert len(factory.return_value.call_args.kwargs["callbacks"]) == 1
    reset_tracing_for_tests()


async def test_bounded_shutdown_does_not_block_following_cleanup(monkeypatch) -> None:
    """A blackholed exporter flush must bound BOTH the event loop and process
    exit (sec-vc-r2-1): the flush runs on a daemon thread, so a hung
    shutdown_tracing neither blocks this coroutine past ~5s nor pins the
    interpreter alive."""
    import threading
    import time

    import core.tracing as tracing

    release = threading.Event()

    def hung_shutdown(timeout_ms: int = 5000) -> None:
        release.wait(timeout=30)

    monkeypatch.setattr(tracing, "shutdown_tracing", hung_shutdown)
    started = time.monotonic()
    await _shutdown_tracing_bounded()
    elapsed = time.monotonic() - started
    try:
        # Returned promptly despite the hung flush; transport.close() can run.
        assert elapsed < 8
        flushers = [t for t in threading.enumerate() if t.name == "tracing-flush"]
        # The flusher is a daemon thread — it cannot pin interpreter exit.
        assert all(t.daemon for t in flushers)
    finally:
        release.set()


# ---------------------------------------------------------------------------
# S-3b: drive the REAL production wiring (build_message_handler) on both ACK
# paths — root spans, attributes, and the failure-mode taxonomy.
# ---------------------------------------------------------------------------


class _Message:
    def __init__(self) -> None:
        self.headers: dict = {}
        self.acked = False
        self.rejected = False

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = True) -> None:
        self.rejected = True


class _MainConfig(BaseConfig):
    rabbitmq_exchange: str = "test-exchange"
    rabbitmq_result_routing_key: str = "test-result"
    rabbitmq_input_queue: str = "test-queue"
    rabbitmq_max_retries: int = 1
    pipeline_timeout: int = 1


def _wiring(plugin_handle, plugin_type: str = "guidance"):
    import asyncio as _asyncio
    from unittest.mock import AsyncMock

    from core.router import Router
    from main import build_message_handler

    plugin = MagicMock()
    plugin.name = plugin_type
    plugin.handle = plugin_handle
    transport = AsyncMock()
    router = Router(plugin_type=plugin_type)
    active: set[_asyncio.Task] = set()
    config = _MainConfig(
        llm_base_url="http://local-model",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
    )
    handler = build_message_handler(
        config=config, plugin=plugin, router=router,
        transport=transport, active_tasks=active,
    )
    return handler, active, config


def _query_body() -> dict:
    from tests.conftest import make_input

    return {"input": make_input().model_dump(by_alias=True)}


async def test_late_ack_path_emits_ok_root_span(traced_exporter) -> None:
    async def handle(event):
        from core.events.response import Response

        return Response(result="ok")

    handler, _, _ = _wiring(handle)
    message = _Message()
    await handler(_query_body(), message)
    shutdown_tracing()
    root = next(s for s in traced_exporter.get_finished_spans() if s.name == "vc.handle")
    assert message.acked
    assert root.attributes["vc.plugin"] == "guidance"
    assert root.attributes["vc.event_type"] == "Input"
    assert root.attributes["vc.engine"]
    assert root.status.status_code.name == "OK"


async def test_late_ack_pipeline_timeout_classifies_timeout(traced_exporter) -> None:
    import asyncio as _asyncio

    async def handle(event):
        await _asyncio.sleep(5)

    handler, _, _ = _wiring(handle)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    root = next(s for s in traced_exporter.get_finished_spans() if s.name == "vc.handle")
    assert root.status.status_code.name == "ERROR"
    assert root.attributes["vc.failure_mode"] == "timeout"


async def test_late_ack_llm_provider_timeout_classifies_llm_error(traced_exporter) -> None:
    """sec-vc-r2-2/S-4b: an adapter timeout must NOT be swallowed by the
    asyncio.TimeoutError branch (Python 3.13 alias)."""
    from core.tracing import LLMInvocationTimeoutError

    async def handle(event):
        raise LLMInvocationTimeoutError("LLM call timed out after 120s")

    handler, _, _ = _wiring(handle)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    root = next(s for s in traced_exporter.get_finished_spans() if s.name == "vc.handle")
    assert root.status.status_code.name == "ERROR"
    assert root.attributes["vc.failure_mode"] == "llm_error"


async def test_late_ack_connection_error_classifies_llm_error(traced_exporter) -> None:
    async def handle(event):
        raise ConnectionError("provider unreachable")

    handler, _, _ = _wiring(handle)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    root = next(s for s in traced_exporter.get_finished_spans() if s.name == "vc.handle")
    assert root.attributes["vc.failure_mode"] == "llm_error"


async def test_early_ack_ingest_path_emits_root_span_and_no_cross_parenting(
    traced_exporter,
) -> None:
    import asyncio as _asyncio

    started = _asyncio.Event()

    async def handle(event):
        started.set()
        from core.events.ingest_website import IngestionResult, IngestWebsiteResult

        return IngestWebsiteResult(result=IngestionResult.SUCCESS)

    handler, active, _ = _wiring(handle, plugin_type="ingest-website")
    body = {
        "eventType": "IngestWebsite",
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "persona-789",
    }
    m1, m2 = _Message(), _Message()
    await handler(dict(body), m1)
    await handler(dict(body), m2)
    assert m1.acked and m2.acked  # early ACK before processing
    if active:
        await _asyncio.gather(*active)
    shutdown_tracing()
    roots = [s for s in traced_exporter.get_finished_spans() if s.name == "vc.handle"]
    assert len(roots) == 2
    # Two concurrent ingest tasks must not share a trace (no cross-parenting).
    assert roots[0].context.trace_id != roots[1].context.trace_id
    for root in roots:
        assert root.attributes["vc.event_type"] == "IngestWebsite"
        assert root.status.status_code.name == "OK"
