"""Tests for RabbitMQ early ACK + async dispatch behaviour.

These tests validate the core behavioural change introduced in spec 008:
messages are ACK'd immediately after JSON parsing succeeds, and the
callback runs as a background asyncio task with an optional outer timeout.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from core.adapters.rabbitmq import RabbitMQAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter() -> RabbitMQAdapter:
    """Create an adapter with dummy connection params."""
    return RabbitMQAdapter(
        host="localhost",
        port=5672,
        user="guest",
        password="guest",
        exchange_name="test-exchange",
    )


def _make_message(body: dict | bytes | str) -> MagicMock:
    """Build a mock aio-pika incoming message."""
    msg = MagicMock()
    if isinstance(body, dict):
        msg.body = json.dumps(body).encode("utf-8")
    elif isinstance(body, str):
        msg.body = body.encode("utf-8")
    else:
        msg.body = body
    msg.headers = {}
    msg.content_type = "application/json"
    msg.ack = AsyncMock()
    msg.reject = AsyncMock()
    return msg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_valid_message_acked_before_callback():
    """A valid JSON message is ACK'd before the callback starts executing."""
    adapter = _make_adapter()

    ack_order: list[str] = []

    async def slow_callback(body: dict) -> None:
        ack_order.append("callback_start")
        await asyncio.sleep(0.05)
        ack_order.append("callback_end")

    # Simulate what consume() sets up internally: we'll call on_message directly.
    # We need to set up the adapter's inflight tasks set, then invoke the inner
    # on_message handler the same way consume() would wire it.

    message = _make_message({"key": "value"})

    # Patch the ack to record ordering
    original_ack = message.ack

    async def recording_ack() -> None:
        ack_order.append("ack")
        await original_ack()

    message.ack = recording_ack

    # Wire up the adapter's internal state as consume() would
    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    adapter._channel = mock_channel
    adapter._exchange = mock_exchange

    # Capture the on_message handler registered with the queue
    registered_handler = None

    async def capture_consume(handler):
        nonlocal registered_handler
        registered_handler = handler

    mock_queue.consume = capture_consume
    mock_queue.bind = AsyncMock()

    await adapter.consume("test-queue", slow_callback, pipeline_timeout=60.0)
    assert registered_handler is not None

    # Invoke the handler with our mock message
    await registered_handler(message)

    # Give the background task a moment to start
    await asyncio.sleep(0.01)

    # ACK must come before callback_start
    assert "ack" in ack_order
    assert ack_order.index("ack") < ack_order.index("callback_start")

    # Wait for task to finish
    await adapter.drain_tasks(timeout=5.0)
    assert ack_order == ["ack", "callback_start", "callback_end"]


async def test_invalid_json_nacked():
    """A non-JSON message is NACK'd (rejected) without running the callback."""
    adapter = _make_adapter()
    callback = AsyncMock()

    message = _make_message(b"not valid json {{{")

    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    adapter._channel = mock_channel
    adapter._exchange = mock_exchange

    registered_handler = None

    async def capture_consume(handler):
        nonlocal registered_handler
        registered_handler = handler

    mock_queue.consume = capture_consume
    mock_queue.bind = AsyncMock()

    await adapter.consume("test-queue", callback, pipeline_timeout=60.0)
    assert registered_handler is not None

    await registered_handler(message)

    # Message should be rejected, not ACK'd
    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()

    # Callback should never have been called
    callback.assert_not_awaited()


async def test_pipeline_timeout_fires():
    """A callback that exceeds pipeline_timeout triggers TimeoutError logging."""
    adapter = _make_adapter()

    timed_out = asyncio.Event()

    async def slow_callback(body: dict) -> None:
        try:
            await asyncio.sleep(10.0)  # Way longer than timeout
        except asyncio.CancelledError:
            timed_out.set()
            raise

    message = _make_message({"key": "value"})

    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    adapter._channel = mock_channel
    adapter._exchange = mock_exchange

    registered_handler = None

    async def capture_consume(handler):
        nonlocal registered_handler
        registered_handler = handler

    mock_queue.consume = capture_consume
    mock_queue.bind = AsyncMock()

    # Very short timeout to trigger quickly in tests
    await adapter.consume("test-queue", slow_callback, pipeline_timeout=0.1)
    assert registered_handler is not None

    # Dispatch the message
    await registered_handler(message)

    # Message should be ACK'd (early ACK)
    message.ack.assert_awaited_once()

    # Wait for the background task to hit the timeout
    await adapter.drain_tasks(timeout=2.0)

    # The task should have completed (via timeout) -- no remaining inflight
    assert len(adapter._inflight_tasks) == 0


async def test_graceful_shutdown_drains_tasks():
    """drain_tasks() waits for pending work to finish."""
    adapter = _make_adapter()

    completed = asyncio.Event()

    async def moderate_callback(body: dict) -> None:
        await asyncio.sleep(0.1)
        completed.set()

    message = _make_message({"key": "value"})

    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    adapter._channel = mock_channel
    adapter._exchange = mock_exchange

    registered_handler = None

    async def capture_consume(handler):
        nonlocal registered_handler
        registered_handler = handler

    mock_queue.consume = capture_consume
    mock_queue.bind = AsyncMock()

    await adapter.consume("test-queue", moderate_callback, pipeline_timeout=60.0)
    assert registered_handler is not None

    await registered_handler(message)

    # There should be an inflight task
    assert len(adapter._inflight_tasks) >= 1

    # Drain should wait for the task
    await adapter.drain_tasks(timeout=5.0)
    assert completed.is_set()
    assert len(adapter._inflight_tasks) == 0


async def test_callback_exception_does_not_crash_consumer():
    """An exception in the callback does not prevent future message processing."""
    adapter = _make_adapter()

    call_count = 0

    async def failing_callback(body: dict) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Simulated pipeline failure")

    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    adapter._channel = mock_channel
    adapter._exchange = mock_exchange

    registered_handler = None

    async def capture_consume(handler):
        nonlocal registered_handler
        registered_handler = handler

    mock_queue.consume = capture_consume
    mock_queue.bind = AsyncMock()

    await adapter.consume("test-queue", failing_callback, pipeline_timeout=60.0)
    assert registered_handler is not None

    # Send two messages -- both should be processed despite the first failing
    msg1 = _make_message({"msg": "first"})
    msg2 = _make_message({"msg": "second"})

    await registered_handler(msg1)
    await registered_handler(msg2)

    # Both messages should be ACK'd
    msg1.ack.assert_awaited_once()
    msg2.ack.assert_awaited_once()

    # Drain and verify both callbacks ran
    await adapter.drain_tasks(timeout=5.0)
    assert call_count == 2


async def test_drain_tasks_no_pending():
    """drain_tasks() completes immediately when there are no pending tasks."""
    adapter = _make_adapter()
    # Should not raise or hang
    await adapter.drain_tasks(timeout=1.0)
    assert len(adapter._inflight_tasks) == 0


async def test_drain_tasks_cancels_on_timeout():
    """drain_tasks() cancels tasks that exceed the drain timeout."""
    adapter = _make_adapter()

    async def infinite_callback(body: dict) -> None:
        await asyncio.sleep(1000)  # Effectively infinite

    message = _make_message({"key": "value"})

    mock_channel = AsyncMock()
    mock_exchange = AsyncMock()
    mock_queue = AsyncMock()
    mock_channel.declare_queue = AsyncMock(return_value=mock_queue)

    adapter._channel = mock_channel
    adapter._exchange = mock_exchange

    registered_handler = None

    async def capture_consume(handler):
        nonlocal registered_handler
        registered_handler = handler

    mock_queue.consume = capture_consume
    mock_queue.bind = AsyncMock()

    # No pipeline_timeout so the callback will run forever (simulating
    # a task that ignores the pipeline timeout for test purposes)
    await adapter.consume("test-queue", infinite_callback, pipeline_timeout=None)
    assert registered_handler is not None

    await registered_handler(message)
    assert len(adapter._inflight_tasks) >= 1

    # Drain with a very short timeout -- should cancel the stuck task
    await adapter.drain_tasks(timeout=0.2)

    # All tasks should be cleaned up
    assert len(adapter._inflight_tasks) == 0
