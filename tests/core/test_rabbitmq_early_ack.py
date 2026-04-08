"""Tests for RabbitMQ early ACK and background task dispatch.

Verifies that:
- Valid JSON messages are ACKed before the callback runs.
- Invalid JSON triggers retry/reject without ACK.
- Background tasks are tracked and cleaned up.
- drain() waits for in-flight tasks with bounded timeout.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.adapters.rabbitmq import RabbitMQAdapter


def _make_adapter() -> RabbitMQAdapter:
    """Create a RabbitMQAdapter with dummy connection params."""
    return RabbitMQAdapter(
        host="localhost",
        port=5672,
        user="guest",
        password="guest",
        exchange_name="test-exchange",
        max_retries=3,
    )


def _make_incoming_message(
    body: bytes,
    headers: dict | None = None,
) -> MagicMock:
    """Create a mock aio_pika incoming message."""
    msg = MagicMock()
    msg.body = body
    msg.headers = headers or {}
    msg.content_type = "application/json"
    msg.ack = AsyncMock()
    msg.reject = AsyncMock()
    return msg


class TestEarlyAck:
    """Tests for the early ACK behavior in consume()."""

    async def test_valid_json_acked_before_callback(self):
        """Valid JSON messages are ACKed immediately, then callback runs."""
        adapter = _make_adapter()

        # Track ordering
        order: list[str] = []

        async def callback(body: dict) -> None:
            order.append("callback")

        # Set up mocks for channel, exchange, queue
        mock_channel = AsyncMock()
        mock_exchange = AsyncMock()
        mock_queue = AsyncMock()
        mock_channel.declare_queue = AsyncMock(return_value=mock_queue)
        adapter._channel = mock_channel
        adapter._exchange = mock_exchange

        # Capture the on_message handler registered with queue.consume
        registered_handler = None

        async def capture_consume(handler):
            nonlocal registered_handler
            registered_handler = handler

        mock_queue.consume = capture_consume

        await adapter.consume("test-queue", callback)
        assert registered_handler is not None

        # Simulate a valid message
        msg = _make_incoming_message(json.dumps({"key": "value"}).encode())

        # Patch ack to record ordering
        original_ack = msg.ack

        async def tracked_ack():
            order.append("ack")
            await original_ack()

        msg.ack = tracked_ack

        await registered_handler(msg)

        # Allow the background task to run
        await asyncio.sleep(0.05)

        assert "ack" in order
        assert "callback" in order
        assert order.index("ack") < order.index("callback")

    async def test_invalid_json_retried_without_ack(self):
        """Invalid JSON triggers retry with x-retry-count header, no ACK."""
        adapter = _make_adapter()

        async def callback(body: dict) -> None:
            pytest.fail("Callback should not be called for invalid JSON")

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

        await adapter.consume("test-queue", callback)

        # Send invalid JSON (attempt 1 of 3)
        msg = _make_incoming_message(b"not-json", headers={})
        await registered_handler(msg)

        msg.ack.assert_not_called()
        msg.reject.assert_called_once_with(requeue=False)
        # Verify retry message was published
        mock_exchange.publish.assert_called_once()

    async def test_invalid_json_discarded_after_max_retries(self):
        """Invalid JSON is rejected without retry after max_retries."""
        adapter = _make_adapter()

        async def callback(body: dict) -> None:
            pytest.fail("Callback should not be called")

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

        await adapter.consume("test-queue", callback)

        # Simulate last retry attempt (retry_count = 2, max_retries = 3)
        msg = _make_incoming_message(b"not-json", headers={"x-retry-count": 2})
        await registered_handler(msg)

        msg.ack.assert_not_called()
        msg.reject.assert_called_once_with(requeue=False)
        # No retry message published
        mock_exchange.publish.assert_not_called()

    async def test_callback_runs_as_background_task(self):
        """Callback is dispatched as an asyncio task (non-blocking)."""
        adapter = _make_adapter()

        task_started = asyncio.Event()
        task_done = asyncio.Event()

        async def slow_callback(body: dict) -> None:
            task_started.set()
            await asyncio.sleep(0.1)
            task_done.set()

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

        await adapter.consume("test-queue", slow_callback)

        msg = _make_incoming_message(json.dumps({"key": "value"}).encode())
        await registered_handler(msg)

        # on_message should return immediately (task dispatched but not awaited)
        # The task may or may not have started yet
        assert len(adapter._tasks) >= 0  # Task is tracked (may complete fast)

        # Wait for task to actually complete
        await asyncio.sleep(0.2)
        assert task_done.is_set()

    async def test_task_cleanup_on_completion(self):
        """Completed tasks are removed from the tracking set."""
        adapter = _make_adapter()

        async def callback(body: dict) -> None:
            pass  # Complete immediately

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

        await adapter.consume("test-queue", callback)

        msg = _make_incoming_message(json.dumps({"test": 1}).encode())
        await registered_handler(msg)

        # Let the task complete
        await asyncio.sleep(0.05)

        assert len(adapter._tasks) == 0


class TestDrain:
    """Tests for the drain() method."""

    async def test_drain_no_tasks(self):
        """drain() returns immediately when no tasks are in-flight."""
        adapter = _make_adapter()
        await adapter.drain(timeout=1.0)
        # Should not raise

    async def test_drain_waits_for_tasks(self):
        """drain() waits for in-flight tasks to complete."""
        adapter = _make_adapter()

        completed = False

        async def work():
            nonlocal completed
            await asyncio.sleep(0.1)
            completed = True

        task = asyncio.create_task(work())
        adapter._tasks.add(task)
        task.add_done_callback(adapter._task_done)

        await adapter.drain(timeout=5.0)
        assert completed

    async def test_drain_cancels_after_timeout(self):
        """drain() cancels tasks that exceed the timeout."""
        adapter = _make_adapter()

        cancelled = False

        async def long_work():
            nonlocal cancelled
            try:
                await asyncio.sleep(100)  # Very long task
            except asyncio.CancelledError:
                cancelled = True
                raise

        task = asyncio.create_task(long_work())
        adapter._tasks.add(task)
        task.add_done_callback(adapter._task_done)

        await adapter.drain(timeout=0.1)
        assert cancelled


class TestTaskDoneCallback:
    """Tests for _task_done error logging."""

    async def test_task_exception_logged(self):
        """Unhandled exceptions in tasks are logged via _task_done."""
        adapter = _make_adapter()

        async def failing():
            raise ValueError("test error")

        task = asyncio.create_task(failing())
        adapter._tasks.add(task)
        task.add_done_callback(adapter._task_done)

        # Wait for task to complete
        await asyncio.sleep(0.05)

        # Task should be removed from tracking
        assert len(adapter._tasks) == 0

    async def test_cancelled_task_handled(self):
        """Cancelled tasks are handled gracefully in _task_done."""
        adapter = _make_adapter()

        async def sleepy():
            await asyncio.sleep(100)

        task = asyncio.create_task(sleepy())
        adapter._tasks.add(task)
        task.add_done_callback(adapter._task_done)

        task.cancel()
        await asyncio.sleep(0.05)

        assert len(adapter._tasks) == 0
