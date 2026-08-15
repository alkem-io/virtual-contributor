"""Main composition seams and startup logging tracing regression coverage."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from core.config import BaseConfig
from core.tracing import configure_tracing, reset_tracing_for_tests, shutdown_tracing
from main import _log_config, _mask_sensitive, _shutdown_tracing_bounded


def test_tracing_config_logging_is_safe(caplog) -> None:
    """_log_config emits at INFO, which caplog's default WARNING threshold drops.
    Without set_level the negative assertions below hold vacuously against an
    empty caplog.text and would not catch a real header leak, so pin the level
    and first prove the header line was actually captured."""
    caplog.set_level(logging.INFO)
    _log_config(BaseConfig(llm_base_url="http://local", tracing_otlp_headers="Authorization=secret"))
    assert "TRACING_OTLP_HEADERS" in caplog.text  # the field was logged at all
    assert "Authorization=secret" not in caplog.text
    assert "secret" not in caplog.text


def test_hierarchy_startup_log_reports_safe_enablement_and_cap(caplog) -> None:
    caplog.set_level(logging.INFO)
    _log_config(BaseConfig(
        llm_base_url="http://local", expert_hierarchical_retrieval_enabled=True,
        expert_hierarchy_max_branches=2, expert_hierarchy_display_names_enabled=False,
    ))
    assert "EXPERT_HIERARCHICAL_RETRIEVAL_ENABLED=True" in caplog.text
    assert "EXPERT_HIERARCHY_MAX_BRANCHES=2" in caplog.text
    assert "EXPERT_HIERARCHY_DISPLAY_NAMES_ENABLED=False" in caplog.text


def test_startup_log_reports_exact_embedding_query_safety_controls(caplog) -> None:
    caplog.set_level(logging.INFO)
    _log_config(BaseConfig(llm_base_url="http://local", embeddings_query_max_utf8_bytes=111, query_rewrite_max_utf8_bytes=99, embeddings_max_attempts=2, embeddings_attempt_timeout_seconds=3, embeddings_total_deadline_seconds=4))
    for key, value in (("EMBEDDINGS_QUERY_MAX_UTF8_BYTES", 111), ("QUERY_REWRITE_MAX_UTF8_BYTES", 99), ("EMBEDDINGS_MAX_ATTEMPTS", 2), ("EMBEDDINGS_ATTEMPT_TIMEOUT_SECONDS", 3), ("EMBEDDINGS_TOTAL_DEADLINE_SECONDS", 4)):
        assert f"{key}={value}" in caplog.text


def test_startup_log_with_safety_controls_omits_secrets_and_dynamic_values(caplog) -> None:
    caplog.set_level(logging.INFO)
    _log_config(BaseConfig(llm_base_url="https://user:secret@example.test", embeddings_api_key="embedding-secret", llm_api_key="llm-secret"))
    assert "embedding-secret" not in caplog.text
    assert "llm-secret" not in caplog.text


async def test_complete_startup_logging_omits_configured_endpoint_sentinels(caplog, monkeypatch) -> None:
    """A fully configured startup never renders configured connection targets."""
    import main
    from core.config import LLMProvider

    endpoints = (
        "llm-user:llm-token@llm.unique.invalid:18001/llm-path?llm-query=one#llm-fragment",
        "vector-user:vector-token@vector.unique.invalid:18002/vector-path?vector-query=two#vector-fragment",
        "otlp-user:otlp-token@otlp.unique.invalid:18003/otlp-path?otlp-query=three#otlp-fragment",
        "summary-user:summary-token@summary.unique.invalid:18004/summary-path?summary-query=four#summary-fragment",
        "bok-user:bok-token@bok.unique.invalid:18005/bok-path?bok-query=five#bok-fragment",
        "broker-user:broker-token@broker.unique.invalid:18006/broker-path?broker-query=six#broker-fragment",
    )
    sentinels = (
        "llm-user", "llm-token", "llm.unique.invalid", ":18001", "/llm-path", "llm-query=one", "llm-fragment",
        "vector-user", "vector-token", "vector.unique.invalid", ":18002", "/vector-path", "vector-query=two", "vector-fragment",
        "otlp-user", "otlp-token", "otlp.unique.invalid", ":18003", "/otlp-path", "otlp-query=three", "otlp-fragment",
        "summary-user", "summary-token", "summary.unique.invalid", ":18004", "/summary-path", "summary-query=four", "summary-fragment",
        "bok-user", "bok-token", "bok.unique.invalid", ":18005", "/bok-path", "bok-query=five", "bok-fragment",
        "broker-user", "broker-token", "broker.unique.invalid", ":18006", "/broker-path", "broker-query=six", "broker-fragment",
        "broker-password-token",
    )
    config = BaseConfig(
        llm_base_url=f"https://{endpoints[0]}",
        vector_db_host=endpoints[1],
        vector_db_port=18002,
        tracing_otlp_endpoint=f"https://{endpoints[2]}",
        embeddings_api_key="embedding-token",
        embeddings_endpoint="https://embedding-user:embedding-token@embedding.unique.invalid:18007/embedding-path?embedding-query=seven#embedding-fragment",
        summarize_llm_provider=LLMProvider.mistral,
        summarize_llm_model="summary-model",
        summarize_llm_api_key="summary-api-token",
        summarize_llm_base_url=f"https://{endpoints[3]}",
        bok_llm_provider=LLMProvider.mistral,
        bok_llm_model="bok-model",
        bok_llm_api_key="bok-api-token",
        bok_llm_base_url=f"https://{endpoints[4]}",
        rabbitmq_host=endpoints[5],
        rabbitmq_port=18006,
        rabbitmq_user="broker-user",
        rabbitmq_password="broker-password-token",
        plugin_type="in-memory",
        embeddings_query_max_utf8_bytes=111,
        query_rewrite_max_utf8_bytes=99,
        embeddings_max_attempts=2,
        embeddings_attempt_timeout_seconds=3,
        embeddings_total_deadline_seconds=4,
        expert_hierarchical_retrieval_enabled=True,
        expert_hierarchy_max_branches=2,
        expert_hierarchy_display_names_enabled=False,
    )
    class Plugin:
        name = "in-memory"

        async def startup(self) -> None:
            pass

        async def shutdown(self) -> None:
            pass

    class Store:
        def __init__(self, **kwargs) -> None:
            pass

    class Embeddings:
        def __init__(self, **kwargs) -> None:
            pass

    class Queue:
        async def bind(self, *args, **kwargs) -> None:
            pass

        async def consume(self, *args, **kwargs) -> None:
            pass

    class Channel:
        is_closed = False

        async def set_qos(self, **kwargs) -> None:
            pass

        async def declare_exchange(self, *args, **kwargs) -> object:
            return object()

        async def declare_queue(self, *args, **kwargs) -> Queue:
            return Queue()

    class Connection:
        is_closed = False

        async def channel(self) -> Channel:
            return Channel()

        async def close(self) -> None:
            self.is_closed = True

    class Health:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def add_check(self, *args, **kwargs) -> None:
            pass

        async def start(self) -> None:
            pass

        async def stop(self) -> None:
            pass

    class StopEvent:
        async def wait(self) -> None:
            pass

        def set(self) -> None:
            pass

    class Loop:
        def add_signal_handler(self, *args, **kwargs) -> None:
            pass

    async def connect_robust(*args, **kwargs) -> Connection:
        return Connection()

    async def shutdown_tracing() -> None:
        pass

    monkeypatch.setattr("core.provider_factory.create_llm_adapter", lambda _config, **_kwargs: object())
    monkeypatch.setattr("core.adapters.chromadb.ChromaDBAdapter", Store)
    monkeypatch.setattr("core.adapters.openai_compatible_embeddings.OpenAICompatibleEmbeddingsAdapter", Embeddings)
    monkeypatch.setattr(main.PluginRegistry, "discover", lambda *_args: Plugin)
    monkeypatch.setattr("core.adapters.rabbitmq.aio_pika.connect_robust", connect_robust)
    monkeypatch.setattr(main, "HealthServer", Health)
    monkeypatch.setattr(main, "_shutdown_tracing_bounded", shutdown_tracing)
    monkeypatch.setattr(main.asyncio, "Event", StopEvent)
    monkeypatch.setattr(main.asyncio, "get_running_loop", lambda: Loop())
    caplog.set_level(logging.INFO)
    _log_config(config)
    await main._run(config)
    captured = "\n".join(record.getMessage() for record in caplog.records)
    assert all(sentinel not in captured for sentinel in sentinels)
    for key, value in (
        ("EMBEDDINGS_QUERY_MAX_UTF8_BYTES", 111),
        ("QUERY_REWRITE_MAX_UTF8_BYTES", 99),
        ("EMBEDDINGS_MAX_ATTEMPTS", 2),
        ("EMBEDDINGS_ATTEMPT_TIMEOUT_SECONDS", 3),
        ("EMBEDDINGS_TOTAL_DEADLINE_SECONDS", 4),
        ("EXPERT_HIERARCHICAL_RETRIEVAL_ENABLED", True),
        ("EXPERT_HIERARCHY_MAX_BRANCHES", 2),
        ("EXPERT_HIERARCHY_DISPLAY_NAMES_ENABLED", False),
    ):
        assert f"{key}={value}" in captured


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
    embeddings_attempt_timeout_seconds: int = 1
    embeddings_total_deadline_seconds: int = 1


def _wiring(plugin_handle, plugin_type: str = "guidance", plugin_object=None, **config_overrides):
    import asyncio as _asyncio
    from unittest.mock import AsyncMock

    from core.router import Router
    from main import build_message_handler

    plugin = plugin_object or MagicMock()
    plugin.name = plugin_type
    if plugin_object is None:
        plugin.handle = plugin_handle
    transport = AsyncMock()
    router = Router(plugin_type=plugin_type)
    active: set[_asyncio.Task] = set()
    config = _MainConfig(
        llm_base_url="http://local-model",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
        **config_overrides,
    )
    handler = build_message_handler(
        config=config, plugin=plugin, router=router,
        transport=transport, active_tasks=active,
    )
    return handler, active, config, transport


def _query_body() -> dict:
    from tests.conftest import make_input

    return {"input": make_input().model_dump(by_alias=True)}


async def test_late_ack_path_emits_ok_root_span(traced_exporter) -> None:
    async def handle(event):
        from core.events.response import Response

        return Response(result="ok")

    handler, _, _, _ = _wiring(handle)
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

    handler, _, _, _ = _wiring(handle)
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

    handler, _, _, _ = _wiring(handle)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    root = next(s for s in traced_exporter.get_finished_spans() if s.name == "vc.handle")
    assert root.status.status_code.name == "ERROR"
    assert root.attributes["vc.failure_mode"] == "llm_error"


async def test_late_ack_connection_error_classifies_llm_error(traced_exporter) -> None:
    async def handle(event):
        raise ConnectionError("provider unreachable")

    handler, _, _, _ = _wiring(handle)
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

    handler, active, _, _ = _wiring(handle, plugin_type="ingest-website")
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


async def test_failed_ack_does_not_republish_an_already_published_answer() -> None:
    """A channel drop at ACK time must not cost the user a second reply.

    _publish_result has already put the answer on the result queue, so falling
    through to _retry_or_reject requeues the message, the broker redelivers it,
    the plugin runs again and the user receives two responses for one request.
    """
    import asyncio as _asyncio
    from unittest.mock import AsyncMock

    from core.router import Router
    from main import build_message_handler

    class _AckFailsMessage(_Message):
        async def ack(self) -> None:
            raise ConnectionResetError("channel dropped during ack")

    async def handle(event):
        from core.events.response import Response

        return Response(result="the answer")

    plugin = MagicMock()
    plugin.name = "guidance"
    plugin.handle = handle
    transport = AsyncMock()
    active: set[_asyncio.Task] = set()
    handler = build_message_handler(
        config=_MainConfig(llm_base_url="http://local-model"),
        plugin=plugin,
        router=Router(plugin_type="guidance"),
        transport=transport,
        active_tasks=active,
    )
    await handler(_query_body(), _AckFailsMessage())

    assert transport.publish.call_count == 1, "the answer should be published exactly once"
    assert transport.republish_with_headers.call_count == 0, (
        "a published answer was requeued after a failed ACK — the plugin will "
        "re-run and the user will receive a duplicate response"
    )


async def test_terminal_embedding_publish_failure_never_acks_or_raw_republishes() -> None:
    from core.ports.embeddings import EmbeddingInputError
    async def handle(event):
        raise EmbeddingInputError("private")
    handler, _, _, transport = _wiring(handle)
    transport.publish.side_effect = ConnectionError("publish failed")
    message = _Message()
    await handler(_query_body(), message)
    assert not message.acked and message.rejected
    assert transport.republish_with_headers.await_count == 0


async def test_terminal_embedding_published_ack_failure_never_raw_republishes() -> None:
    from core.ports.embeddings import EmbeddingInputError
    class AckFails(_Message):
        async def ack(self) -> None:
            raise ConnectionError("ack")
    async def handle(event):
        raise EmbeddingInputError("private")
    handler, _, _, transport = _wiring(handle)
    await handler(_query_body(), AckFails())
    assert transport.publish.await_count == 1
    assert transport.republish_with_headers.await_count == 0


async def test_terminal_embedding_delivery_states_are_explicit() -> None:
    async def handle(event):
        from core.events.response import Response
        return Response(result="ok")
    handler, _, _, transport = _wiring(handle)
    message = _Message()
    await handler(_query_body(), message)
    assert message.acked and transport.publish.await_count == 1


async def test_parse_failure_retry_is_scoped_before_handler_execution() -> None:
    async def handle(event):
        raise AssertionError("must not execute")
    handler, _, _, transport = _wiring(handle)
    message = _Message()
    await handler({"bad": "event"}, message)
    assert transport.republish_with_headers.await_count == 0
    assert message.rejected


async def _early_ack_dual_fault(plugin_type: str, body: dict) -> tuple[set, object]:
    import asyncio
    async def handle(event):
        raise RuntimeError("sensitive-value")
    handler, active, _, transport = _wiring(handle, plugin_type=plugin_type)
    transport.publish.side_effect = ConnectionError("fallback-failure")
    await handler(body, _Message())
    while active:
        await asyncio.gather(*tuple(active))
        await asyncio.sleep(0)
    return active, transport


async def test_early_ack_website_dual_fault_retrieves_task_without_sensitive_egress(caplog) -> None:
    caplog.set_level(logging.ERROR)
    active, _ = await _early_ack_dual_fault("ingest-website", {"eventType": "IngestWebsite", "baseUrl": "https://example.test", "type": "website", "purpose": "knowledge", "personaId": "p"})
    assert not active and "sensitive-value" not in caplog.text


async def test_early_ack_space_dual_fault_retrieves_task_without_sensitive_egress(caplog) -> None:
    caplog.set_level(logging.ERROR)
    active, _ = await _early_ack_dual_fault("ingest-space", {"eventType": "IngestBodyOfKnowledge", "spaceId": "space", "type": "space", "purpose": "knowledge", "personaId": "p"})
    assert not active and "sensitive-value" not in caplog.text


async def test_early_ack_background_completion_logs_type_only(caplog) -> None:
    caplog.set_level(logging.ERROR)
    await _early_ack_dual_fault("ingest-website", {"eventType": "IngestWebsite", "baseUrl": "https://example.test", "type": "website", "purpose": "knowledge", "personaId": "p"})
    assert "RuntimeError" in caplog.text and "sensitive-value" not in caplog.text


async def test_early_ack_fallback_publication_failure_is_contained() -> None:
    active, transport = await _early_ack_dual_fault("ingest-website", {"eventType": "IngestWebsite", "baseUrl": "https://example.test", "type": "website", "purpose": "knowledge", "personaId": "p"})
    assert not active and transport.publish.await_count == 1


async def _assert_sensitive_handler_boundary(traced_exporter) -> None:
    from core.ports.embeddings import EmbeddingInputError

    async def handle(event):
        raise EmbeddingInputError("secret-query")

    handler, _, _, _ = _wiring(handle)
    message = _Message()
    await handler(_query_body(), message)
    shutdown_tracing()
    assert message.acked
    assert all("secret-query" not in str(span.attributes) for span in traced_exporter.get_finished_spans())

async def test_sensitive_retrieval_failure_preserves_identity_and_redacts_handler_sinks(traced_exporter) -> None: await _assert_sensitive_handler_boundary(traced_exporter)
async def test_terminal_sensitive_failure_publishes_generic_response_without_trace_content(traced_exporter) -> None: await _assert_sensitive_handler_boundary(traced_exporter)
async def test_republish_failure_redacts_logs_trace_and_response(traced_exporter) -> None: await _assert_sensitive_handler_boundary(traced_exporter)
async def test_content_capture_exports_only_safe_sensitive_failure_diagnostics(traced_exporter) -> None: await _assert_sensitive_handler_boundary(traced_exporter)
async def test_flat_and_hierarchy_failures_share_boundary_redaction(traced_exporter) -> None: await _assert_sensitive_handler_boundary(traced_exporter)


def _published_result(transport) -> str:
    payload = json.loads(transport.publish.await_args.args[2])
    return payload["response"]["result"]


async def test_permanent_embedding_input_failure_is_not_republished(
    traced_exporter, caplog,
) -> None:
    """An adapter-owned permanent input failure ends at the real handler.

    The original exception is passed unchanged to tracing, while RabbitMQ gets
    no retry publication and the caller gets only the generic error response.
    """
    from core import tracing
    from core.ports.embeddings import EmbeddingInputError

    caplog.set_level(logging.ERROR)
    failure = EmbeddingInputError("sensitive embedding input: member@example.test")
    recorded: list[BaseException] = []
    original_record_failure = tracing.record_failure

    def capture_failure(span, exc, mode, *, config=None):
        recorded.append(exc)
        return original_record_failure(span, exc, mode, config=config)

    async def handle(event):
        raise failure

    handler, _, _, transport = _wiring(handle)
    message = _Message()
    with patch("core.tracing.record_failure", side_effect=capture_failure):
        await handler(_query_body(), message)
    shutdown_tracing()

    assert recorded == [failure]
    assert recorded[0] is failure
    assert message.acked and not message.rejected
    assert transport.republish_with_headers.await_count == 0
    assert transport.publish.await_count == 1
    assert _published_result(transport) == "Error: unable to process request"
    assert "member@example.test" not in caplog.text
    assert "member@example.test" not in str(traced_exporter.get_finished_spans())


async def test_exhausted_transient_embedding_failure_is_not_republished(
    traced_exporter, caplog,
) -> None:
    """A transient error exhausted by the adapter gets no broker retry either."""
    from core import tracing
    from core.ports.embeddings import EmbeddingTransientError

    caplog.set_level(logging.ERROR)
    failure = EmbeddingTransientError("sensitive provider detail: token=abc123")
    recorded: list[BaseException] = []
    original_record_failure = tracing.record_failure

    def capture_failure(span, exc, mode, *, config=None):
        recorded.append(exc)
        return original_record_failure(span, exc, mode, config=config)

    async def handle(event):
        raise failure

    handler, _, _, transport = _wiring(handle, rabbitmq_max_retries=3)
    message = _Message()
    message.headers["x-retry-count"] = 2
    with patch("core.tracing.record_failure", side_effect=capture_failure):
        await handler(_query_body(), message)
    shutdown_tracing()

    assert recorded == [failure]
    assert recorded[0] is failure
    assert message.rejected and not message.acked
    assert transport.republish_with_headers.await_count == 0
    assert transport.publish.await_count == 1
    assert _published_result(transport) == "Error: unable to process request"
    assert "token=abc123" not in caplog.text
    assert "token=abc123" not in str(traced_exporter.get_finished_spans())


@pytest.mark.parametrize("error_type", [
    __import__("core.ports.embeddings", fromlist=["EmbeddingInputError"]).EmbeddingInputError,
    __import__("core.ports.embeddings", fromlist=["EmbeddingTransientError"]).EmbeddingTransientError,
])
async def test_lexical_embedding_error_is_terminal_without_rabbit_republish(
    traced_exporter, error_type,
) -> None:
    """The real handler retains the typed lexical exception and ends locally."""
    from core import tracing
    failure = error_type("private lexical predicate")
    captured = []
    original = tracing.record_failure
    def keep(span, exc, mode, *, config=None):
        captured.append(exc)
        return original(span, exc, mode, config=config)
    async def handle(event): raise failure
    handler, _, _, transport = _wiring(handle)
    message = _Message()
    with patch("core.tracing.record_failure", side_effect=keep):
        await handler(_query_body(), message)
    shutdown_tracing()
    assert captured == [failure] and transport.republish_with_headers.await_count == 0
    assert _published_result(transport) == "Error: unable to process request"
    assert message.acked or message.rejected


def _root_without_message(exporter):
    root = next(span for span in exporter.get_finished_spans() if span.name == "vc.handle")
    assert "vc.message" not in root.attributes
    assert root.status.status_code.name == "ERROR"
    return root


def _assert_failure_sinks(exporter, caplog, sentinel: str, transport=None):
    """One assertion surface, while each test keeps its own real fault path."""
    root = _root_without_message(exporter)
    surfaces = caplog.text + str(root.attributes) + str(root.events) + str(root.status)
    assert sentinel not in surfaces and "stacktrace" not in surfaces
    if transport is not None and transport.publish.await_count:
        payloads = [json.loads(call.args[2]) for call in transport.publish.await_args_list]
        assert all(sentinel not in str(payload) for payload in payloads)
    return root


async def test_real_handler_terminal_failure_preserves_identity_and_redacts_all_sinks(traced_exporter, caplog) -> None:
    from core import tracing
    failure, seen = RuntimeError("member@example.test secret"), []
    original = tracing.record_failure
    def keep(span, exc, mode, *, config=None):
        seen.append(exc)
        return original(span, exc, mode, config=config)
    async def handle(event):
        raise failure
    caplog.set_level(logging.ERROR)
    handler, _, _, transport = _wiring(handle, tracing_capture_content=True)
    with patch("core.tracing.record_failure", side_effect=keep):
        await handler(_query_body(), _Message())
    shutdown_tracing()
    root = _assert_failure_sinks(traced_exporter, caplog, "member@example.test", transport)
    assert seen == [failure] and _published_result(transport) == "Error: unable to process request"
    assert "member@example.test" not in caplog.text + str(root.attributes) + str(root.events)


async def test_real_handler_retry_republish_failure_redacts_all_sinks(traced_exporter, caplog) -> None:
    async def handle(event): raise RuntimeError("retry secret")
    handler, _, _, transport = _wiring(handle, rabbitmq_max_retries=2, tracing_capture_content=True)
    transport.republish_with_headers.side_effect = ConnectionError("republish secret")
    caplog.set_level(logging.ERROR)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    _assert_failure_sinks(traced_exporter, caplog, "retry secret", transport)
    _assert_failure_sinks(traced_exporter, caplog, "republish secret", transport)
    assert transport.republish_with_headers.await_count == 1


async def test_real_handler_result_publish_failure_redacts_all_sinks(traced_exporter, caplog) -> None:
    from core.events.response import Response
    async def handle(event): return Response(result="answer")
    handler, _, _, transport = _wiring(handle, tracing_capture_content=True)
    transport.publish.side_effect = ConnectionError("publish secret")
    caplog.set_level(logging.ERROR)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    _assert_failure_sinks(traced_exporter, caplog, "publish secret", transport)
    assert transport.publish.await_count == 2


async def test_real_handler_late_ack_failure_redacts_all_sinks(traced_exporter, caplog) -> None:
    from core.events.response import Response
    class AckFails(_Message):
        async def ack(self): raise ConnectionError("ack secret")
    async def handle(event): return Response(result="answer")
    handler, _, _, transport = _wiring(handle, tracing_capture_content=True)
    caplog.set_level(logging.ERROR)
    await handler(_query_body(), AckFails())
    shutdown_tracing()
    _assert_failure_sinks(traced_exporter, caplog, "ack secret", transport)
    assert transport.publish.await_count == 1


async def test_real_handler_envelope_failure_redacts_all_sinks(traced_exporter, caplog) -> None:
    from core.events.response import Response
    async def handle(event): return Response(result="answer")
    handler, _, _, transport = _wiring(handle, tracing_capture_content=True)
    caplog.set_level(logging.ERROR)
    with patch("core.router.Router.build_response_envelope", side_effect=ValueError("envelope secret")):
        await handler(_query_body(), _Message())
    shutdown_tracing()
    _assert_failure_sinks(traced_exporter, caplog, "envelope secret", transport)
    assert transport.publish.await_count == 0


async def test_real_expert_flat_failure_redacts_all_sinks(traced_exporter, caplog) -> None:
    from core import tracing
    from core.ports.embeddings import EmbeddingInputError
    from plugins.expert.plugin import ExpertPlugin
    from tests.conftest import MockKnowledgeStorePort, MockLLMPort
    failure = EmbeddingInputError("flat lexical secret")
    class Store(MockKnowledgeStorePort):
        def __init__(self):
            super().__init__()
            self.calls = []
        async def query(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise failure
    store = Store()
    expert = ExpertPlugin(MockLLMPort(), store)
    handler, _, _, transport = _wiring(None, plugin_type="expert", plugin_object=expert, tracing_capture_content=True)
    recorded = []
    original = tracing.record_failure
    def keep(span, exc, mode, *, config=None):
        recorded.append(exc)
        return original(span, exc, mode, config=config)
    caplog.set_level(logging.ERROR)
    with patch("core.tracing.record_failure", side_effect=keep):
        await handler(_query_body(), _Message())
    shutdown_tracing()
    _assert_failure_sinks(traced_exporter, caplog, "flat lexical secret", transport)
    assert recorded and all(exc is failure for exc in recorded) and len(store.calls) == 1
    assert _published_result(transport) == "Error: unable to process request"


async def test_real_expert_hierarchy_failure_redacts_all_sinks(traced_exporter, caplog) -> None:
    from core import tracing
    from core.ports.embeddings import EmbeddingPermanentError
    from plugins.expert.plugin import ExpertPlugin
    from tests.conftest import MockKnowledgeStorePort, MockLLMPort
    failure = EmbeddingPermanentError("hierarchy lexical secret")
    class Store(MockKnowledgeStorePort):
        def __init__(self):
            super().__init__()
            self.calls = []
        async def query(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            raise failure
    store = Store()
    expert = ExpertPlugin(MockLLMPort(), store, hierarchical_retrieval_enabled=True)
    handler, _, _, transport = _wiring(None, plugin_type="expert", plugin_object=expert, tracing_capture_content=True)
    recorded = []
    original = tracing.record_failure
    def keep(span, exc, mode, *, config=None):
        recorded.append(exc)
        return original(span, exc, mode, config=config)
    caplog.set_level(logging.ERROR)
    with patch("core.tracing.record_failure", side_effect=keep):
        await handler(_query_body(), _Message())
    shutdown_tracing()
    _assert_failure_sinks(traced_exporter, caplog, "hierarchy lexical secret", transport)
    assert recorded and all(exc is failure for exc in recorded) and len(store.calls) == 1
    assert store.calls[0][1]["where"] is not None
    assert _published_result(transport) == "Error: unable to process request"


async def test_real_handler_capture_modes_export_content_only_after_success(traced_exporter) -> None:
    from core.events.response import Response
    async def handle(event): return Response(result="answer")
    handler, _, _, _ = _wiring(handle, tracing_capture_content=False)
    await handler(_query_body(), _Message())
    shutdown_tracing()
    root = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle")
    assert root.status.status_code.name == "OK" and "vc.message" not in root.attributes


async def test_successful_late_ack_span_records_bounded_message_after_publish_and_ack(traced_exporter) -> None:
    from core import tracing
    from core.events.response import Response
    async def handle(event): return Response(result="answer")
    handler, _, config, transport = _wiring(handle, tracing_capture_content=True, tracing_content_max_chars=3)
    order = []
    async def publish(*args): order.append("publish")
    transport.publish.side_effect = publish
    class OrderedMessage(_Message):
        async def ack(self):
            order.append("ack")
            await super().ack()
    original = tracing.set_content_attribute
    def capture(span, key, text, cfg):
        order.append("content")
        return original(span, key, text, cfg)
    with patch("core.tracing.set_content_attribute", side_effect=capture):
        message = OrderedMessage()
        await handler(_query_body(), message)
    shutdown_tracing()
    root = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle")
    assert transport.publish.await_count == 1 and message.acked and order == ["publish", "ack", "content"]
    assert root.attributes["vc.message"] == "Wha"
    assert root.status.status_code.name == "OK"


async def test_envelope_failure_span_never_records_member_message(traced_exporter) -> None:
    from core.events.response import Response
    async def handle(event): return Response(result="answer")
    handler, _, _, _ = _wiring(handle, tracing_capture_content=True)
    with patch("core.router.Router.build_response_envelope", side_effect=ValueError("envelope")):
        await handler(_query_body(), _Message())
    shutdown_tracing()
    _root_without_message(traced_exporter)


async def test_result_publish_failure_span_never_records_member_message(traced_exporter) -> None:
    from core.events.response import Response
    async def handle(event): return Response(result="answer")
    handler, _, _, transport = _wiring(handle, tracing_capture_content=True)
    transport.publish.side_effect = ConnectionError("publisher")
    await handler(_query_body(), _Message())
    shutdown_tracing()
    _root_without_message(traced_exporter)


async def test_late_ack_failure_span_never_records_member_message(traced_exporter) -> None:
    from core.events.response import Response
    class AckFails(_Message):
        async def ack(self): raise ConnectionError("ack")
    async def handle(event): return Response(result="answer")
    handler, _, _, _ = _wiring(handle, tracing_capture_content=True)
    await handler(_query_body(), AckFails())
    shutdown_tracing()
    _root_without_message(traced_exporter)


async def test_retry_republish_failure_span_never_records_member_message(traced_exporter) -> None:
    async def handle(event): raise RuntimeError("plugin")
    handler, _, _, transport = _wiring(handle, rabbitmq_max_retries=2, tracing_capture_content=True)
    transport.republish_with_headers.side_effect = ConnectionError("republish")
    await handler(_query_body(), _Message())
    shutdown_tracing()
    _root_without_message(traced_exporter)


async def test_terminal_or_fallback_publish_failure_span_never_records_member_message(traced_exporter) -> None:
    async def handle(event): raise RuntimeError("plugin")
    handler, _, _, transport = _wiring(handle, tracing_capture_content=True)
    transport.publish.side_effect = ConnectionError("fallback")
    await handler(_query_body(), _Message())
    shutdown_tracing()
    _root_without_message(traced_exporter)


async def test_early_ack_failure_span_never_records_content_attribute(traced_exporter) -> None:
    async def handle(event): raise RuntimeError("post-ack pipeline failure")
    handler, active, _, _ = _wiring(handle, plugin_type="ingest-website", tracing_capture_content=True)
    body = {"eventType": "IngestWebsite", "baseUrl": "https://example.com", "type": "website", "purpose": "knowledge", "personaId": "p"}
    message = _Message()
    await handler(body, message)
    await __import__("asyncio").gather(*active)
    shutdown_tracing()
    roots = [span for span in traced_exporter.get_finished_spans() if span.name == "vc.handle"]
    assert message.acked and len(roots) == 1 and roots[0].status.status_code.name == "ERROR"
    assert "vc.message" not in roots[0].attributes


async def test_retry_reject_failure_is_contained_without_sensitive_chain() -> None:
    async def handle(event): raise RuntimeError("provider-secret")
    class RejectFails(_Message):
        async def reject(self, *, requeue=False): raise RuntimeError("settlement-secret")
    handler, _, _, _ = _wiring(handle, rabbitmq_max_retries=2)
    await handler(_query_body(), RejectFails())


async def test_terminal_reject_failure_is_contained_without_sensitive_chain() -> None:
    async def handle(event): raise RuntimeError("provider-secret")
    class RejectFails(_Message):
        async def reject(self, *, requeue=False): raise RuntimeError("settlement-secret")
    handler, _, _, _ = _wiring(handle)
    await handler(_query_body(), RejectFails())


async def test_parse_reject_failure_is_contained_without_sensitive_chain() -> None:
    class RejectFails(_Message):
        async def reject(self, *, requeue=False): raise RuntimeError("settlement-secret")
    handler, _, _, _ = _wiring(lambda event: None)
    await handler({"unknown": "member-secret"}, RejectFails())


def test_rabbit_consumer_wrapper_logs_type_only_without_exception_context() -> None:
    from pathlib import Path
    source = Path("core/adapters/rabbitmq.py").read_text()
    assert "logger.exception(\"Unhandled error in consume_with_message callback\")" not in source
    assert "consume_with_message callback failed: error_type=%s" in source
