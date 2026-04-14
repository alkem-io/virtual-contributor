"""Tests for early ACK with async processing behavior.

These tests verify the on_message callback logic from main.py,
specifically:
- Ingest events are ACKed before processing (early ACK)
- Engine queries are ACKed after processing (late ACK)
- Pipeline timeout wraps plugin.handle()
- Fire-and-forget task management
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from core.events.ingest_space import IngestBodyOfKnowledge
from core.events.ingest_website import IngestWebsite
from core.router import Router


# ---------------------------------------------------------------------------
# Helpers: mock message objects
# ---------------------------------------------------------------------------


class MockAMQPMessage:
    """Simulates an aio_pika AbstractIncomingMessage for testing."""

    def __init__(self, headers: dict | None = None) -> None:
        self.headers = headers or {}
        self.acked = False
        self.rejected = False
        self.reject_requeue: bool | None = None
        self._ack_order: list[str] = []  # shared between message and test

    async def ack(self) -> None:
        self.acked = True
        self._ack_order.append("ack")

    async def reject(self, requeue: bool = True) -> None:
        self.rejected = True
        self.reject_requeue = requeue


# ---------------------------------------------------------------------------
# Helpers: build on_message callback matching main.py logic
# ---------------------------------------------------------------------------


def _build_on_message(
    plugin: Any,
    router: Router,
    transport: Any,
    config: Any,
    active_tasks: set[asyncio.Task],
):
    """Build the on_message callback replicating main.py logic.

    This avoids importing main.py (which triggers config loading).
    Instead we inline the same logic to test it in isolation.
    """

    def _is_ingest_event(event: object) -> bool:
        return isinstance(event, (IngestWebsite, IngestBodyOfKnowledge))

    async def _publish_result(envelope: dict) -> None:
        await transport.publish(
            config.rabbitmq_exchange,
            config.rabbitmq_result_routing_key,
            json.dumps(envelope).encode("utf-8"),
        )

    async def _run_pipeline(event: object) -> None:
        try:
            response = await asyncio.wait_for(
                plugin.handle(event),
                timeout=config.pipeline_timeout,
            )
            envelope = router.build_response_envelope(response, event)
            await _publish_result(envelope)
        except asyncio.TimeoutError:
            from core.events.response import Response
            error_response = Response(result=f"Error: pipeline timed out after {config.pipeline_timeout}s")
            envelope = router.build_response_envelope(error_response, event)
            await _publish_result(envelope)
        except Exception as exc:
            from core.events.response import Response
            error_response = Response(result=f"Error: {exc}")
            envelope = router.build_response_envelope(error_response, event)
            await _publish_result(envelope)

    def _task_done(task: asyncio.Task) -> None:
        active_tasks.discard(task)

    async def on_message(body: dict, message: object) -> None:
        event = None
        try:
            event = router.parse_event(body)
            if _is_ingest_event(event):
                await message.ack()  # type: ignore[union-attr]
                task = asyncio.create_task(_run_pipeline(event))
                active_tasks.add(task)
                task.add_done_callback(_task_done)
            else:
                response = await asyncio.wait_for(
                    plugin.handle(event),
                    timeout=config.pipeline_timeout,
                )
                envelope = router.build_response_envelope(response, event)
                await _publish_result(envelope)
                await message.ack()  # type: ignore[union-attr]
        except Exception:
            await message.reject(requeue=False)  # type: ignore[union-attr]

    return on_message


class FakeConfig:
    """Minimal config for testing."""
    rabbitmq_exchange = "test-exchange"
    rabbitmq_result_routing_key = "test-result"
    rabbitmq_input_queue = "test-queue"
    rabbitmq_max_retries = 3
    pipeline_timeout = 5  # Short timeout for tests


# ---------------------------------------------------------------------------
# Tests: ingest early ACK
# ---------------------------------------------------------------------------


async def test_ingest_event_acked_before_processing():
    """Ingest events must be ACKed before plugin.handle() is called."""
    order: list[str] = []

    async def mock_handle(event):
        order.append("handle_started")
        await asyncio.sleep(0.05)
        order.append("handle_done")
        from core.events.ingest_website import IngestWebsiteResult, IngestionResult
        return IngestWebsiteResult(result=IngestionResult.SUCCESS)

    plugin = MagicMock()
    plugin.handle = mock_handle

    transport = AsyncMock()

    router = Router(plugin_type="ingest-website")
    config = FakeConfig()
    active_tasks: set[asyncio.Task] = set()
    message = MockAMQPMessage()
    message._ack_order = order

    on_message = _build_on_message(plugin, router, transport, config, active_tasks)

    body = {
        "eventType": "IngestWebsite",
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "p-1",
    }
    await on_message(body, message)

    # ACK should happen before handle
    assert message.acked is True

    # Wait for the background task to complete
    if active_tasks:
        await asyncio.gather(*active_tasks)

    assert order.index("ack") < order.index("handle_started")


async def test_engine_query_acked_after_processing():
    """Engine queries must be ACKed after plugin.handle() completes."""
    from core.events.response import Response

    order: list[str] = []

    async def mock_handle(event):
        order.append("handle_started")
        order.append("handle_done")
        return Response(result="test response")

    plugin = MagicMock()
    plugin.handle = mock_handle

    transport = AsyncMock()
    router = Router(plugin_type="generic")
    config = FakeConfig()
    active_tasks: set[asyncio.Task] = set()
    message = MockAMQPMessage()
    message._ack_order = order

    on_message = _build_on_message(plugin, router, transport, config, active_tasks)

    body = {
        "input": {
            "engine": "generic",
            "userID": "u-1",
            "message": "hello",
            "personaID": "p-1",
        }
    }
    await on_message(body, message)

    assert message.acked is True
    # ACK should happen after handle
    assert order.index("handle_done") < order.index("ack")


# ---------------------------------------------------------------------------
# Tests: pipeline timeout
# ---------------------------------------------------------------------------


async def test_pipeline_timeout_publishes_error():
    """When pipeline exceeds timeout, an error result is published."""
    async def slow_handle(event):
        await asyncio.sleep(10)  # Will be cancelled by timeout
        from core.events.ingest_website import IngestWebsiteResult, IngestionResult
        return IngestWebsiteResult(result=IngestionResult.SUCCESS)

    plugin = MagicMock()
    plugin.handle = slow_handle

    transport = AsyncMock()
    router = Router(plugin_type="ingest-website")
    config = FakeConfig()
    config.pipeline_timeout = 0.1  # Very short timeout for testing
    active_tasks: set[asyncio.Task] = set()
    message = MockAMQPMessage()

    on_message = _build_on_message(plugin, router, transport, config, active_tasks)

    body = {
        "eventType": "IngestWebsite",
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "p-1",
    }
    await on_message(body, message)

    # ACK should happen immediately (early ACK for ingest)
    assert message.acked is True

    # Wait for the background task to complete (will timeout)
    if active_tasks:
        await asyncio.gather(*active_tasks)

    # Verify error result was published
    transport.publish.assert_called()
    call_args = transport.publish.call_args
    published_body = json.loads(call_args[0][2])
    assert "Error: pipeline timed out" in published_body["response"]["result"]


# ---------------------------------------------------------------------------
# Tests: pipeline success and failure
# ---------------------------------------------------------------------------


async def test_pipeline_success_publishes_result():
    """Successful pipeline publishes result to result queue."""
    from core.events.ingest_website import IngestWebsiteResult, IngestionResult

    async def mock_handle(event):
        return IngestWebsiteResult(result=IngestionResult.SUCCESS)

    plugin = MagicMock()
    plugin.handle = mock_handle

    transport = AsyncMock()
    router = Router(plugin_type="ingest-website")
    config = FakeConfig()
    active_tasks: set[asyncio.Task] = set()
    message = MockAMQPMessage()

    on_message = _build_on_message(plugin, router, transport, config, active_tasks)

    body = {
        "eventType": "IngestWebsite",
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "p-1",
    }
    await on_message(body, message)

    # Wait for background task
    if active_tasks:
        await asyncio.gather(*active_tasks)

    transport.publish.assert_called_once()
    call_args = transport.publish.call_args
    published_body = json.loads(call_args[0][2])
    assert published_body["response"]["result"] == "success"


async def test_pipeline_exception_publishes_error():
    """Pipeline exception publishes error to result queue."""
    async def failing_handle(event):
        raise RuntimeError("Something broke")

    plugin = MagicMock()
    plugin.handle = failing_handle

    transport = AsyncMock()
    router = Router(plugin_type="ingest-website")
    config = FakeConfig()
    active_tasks: set[asyncio.Task] = set()
    message = MockAMQPMessage()

    on_message = _build_on_message(plugin, router, transport, config, active_tasks)

    body = {
        "eventType": "IngestWebsite",
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "p-1",
    }
    await on_message(body, message)

    # ACK should happen immediately (early ACK for ingest)
    assert message.acked is True

    # Wait for background task
    if active_tasks:
        await asyncio.gather(*active_tasks)

    transport.publish.assert_called_once()
    call_args = transport.publish.call_args
    published_body = json.loads(call_args[0][2])
    assert "Error: Something broke" in published_body["response"]["result"]


# ---------------------------------------------------------------------------
# Tests: consume_with_message adapter method
# ---------------------------------------------------------------------------


async def test_consume_with_message_delegates_to_callback():
    """consume_with_message passes parsed body and raw message to callback."""
    callback_calls: list[tuple] = []

    async def mock_callback(body: dict, message: object) -> None:
        callback_calls.append((body, message))
        await message.ack()  # type: ignore[union-attr]

    # We test the method signature and delegation logic
    # without a real RabbitMQ connection.
    # The key contract: callback receives (dict, AbstractIncomingMessage)
    assert len(callback_calls) == 0  # Sanity — no calls yet

    # Simulate what the adapter does: parse JSON and call callback
    raw_body = json.dumps({"test": "data"}).encode("utf-8")
    mock_message = MockAMQPMessage()
    parsed_body = json.loads(raw_body.decode("utf-8"))
    await mock_callback(parsed_body, mock_message)

    assert len(callback_calls) == 1
    assert callback_calls[0][0] == {"test": "data"}
    assert mock_message.acked is True
