"""RabbitMQ adapter handshake-boundary and queue-name sanitization coverage.

Complements ``tests/core/test_main_tracing.py``'s full-startup captures with
adapter-level controls: staged handshake failures after the connection is
already open (channel/qos/exchange, plus cleanup-failure), and direct calls
into ``consume()``/``consume_with_message()`` proving the queue name never
reaches a log record through either path.
"""

from __future__ import annotations

import json
import logging

import pytest

from core.adapters.rabbitmq import RabbitMQAdapter


#: A value distinctive enough that finding it in a log is unambiguous.
QUEUE_SENTINEL = "sentinel-queue-name-9f3c"


def _adapter() -> RabbitMQAdapter:
    return RabbitMQAdapter(
        host="broker.invalid",
        port=5672,
        user="broker-user",
        password="broker-password",
        exchange_name="exchange-under-test",
    )


class _FailingChannel:
    is_closed = False

    def __init__(self, fail_at: str, exc: Exception) -> None:
        self._fail_at = fail_at
        self._exc = exc

    async def set_qos(self, **kwargs) -> None:
        if self._fail_at == "qos":
            raise self._exc

    async def declare_exchange(self, *args, **kwargs) -> object:
        if self._fail_at == "exchange":
            raise self._exc
        return object()


class _StagedConnection:
    """Stub connection whose ``channel()``/close path is fully controlled."""

    def __init__(
        self,
        fail_at: str,
        exc: Exception,
        close_exc: Exception | None = None,
    ) -> None:
        self._fail_at = fail_at
        self._exc = exc
        self._close_exc = close_exc
        self.is_closed = False
        self.closed_calls = 0

    async def channel(self):
        if self._fail_at == "channel":
            raise self._exc
        return _FailingChannel(self._fail_at, self._exc)

    async def close(self) -> None:
        self.closed_calls += 1
        if self._close_exc is not None:
            raise self._close_exc
        self.is_closed = True


@pytest.mark.parametrize("stage", ["channel", "qos", "exchange"])
async def test_post_connect_stage_failure_is_sanitized_and_closes_connection(
    stage: str, caplog, monkeypatch,
) -> None:
    """A failure after the connection is open still projects only the fixed
    stage/type marker, raises a static cause-free exception, and closes the
    already-opened connection inside the same boundary — for each of the
    three post-connect stages."""
    sentinel_exc = RuntimeError(f"leaky-detail-{stage}-9f3c")
    connection = _StagedConnection(stage, sentinel_exc)

    async def connect_robust(*args, **kwargs):
        return connection

    monkeypatch.setattr(
        "core.adapters.rabbitmq.aio_pika.connect_robust", connect_robust,
    )
    adapter = _adapter()

    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError) as failure:
        await adapter.connect()

    assert str(failure.value) == "RabbitMQ startup failed"
    assert failure.value.__cause__ is None
    assert f"leaky-detail-{stage}-9f3c" not in str(failure.value)

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [(r.msg, r.args, r.exc_info) for r in errors] == [
        (f"RabbitMQ startup failed: stage={stage} error_type=%s", ("RuntimeError",), False),
    ]
    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert f"leaky-detail-{stage}-9f3c" not in rendered

    assert connection.closed_calls == 1
    assert connection.is_closed is True


async def test_cleanup_failure_after_stage_failure_is_also_sanitized(
    caplog, monkeypatch,
) -> None:
    """If closing the connection after a stage failure itself raises, that
    cleanup exception is also projected through the fixed cleanup marker —
    it must never escape unsanitized or leak into the stage-failure
    record."""
    stage_exc = RuntimeError("leaky-stage-detail-9f3c")
    cleanup_exc = ValueError("leaky-cleanup-detail-9f3c")
    connection = _StagedConnection("channel", stage_exc, close_exc=cleanup_exc)

    async def connect_robust(*args, **kwargs):
        return connection

    monkeypatch.setattr(
        "core.adapters.rabbitmq.aio_pika.connect_robust", connect_robust,
    )
    adapter = _adapter()

    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError) as failure:
        await adapter.connect()

    assert failure.value.__cause__ is None
    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert "leaky-stage-detail-9f3c" not in rendered
    assert "leaky-cleanup-detail-9f3c" not in rendered

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    # Cleanup runs (and is logged) before the stage failure itself is logged
    # and raised — the stage log always happens last, right before the raise.
    assert [(r.msg, r.args, r.exc_info) for r in errors] == [
        ("RabbitMQ startup cleanup failed: error_type=%s", ("ValueError",), False),
        ("RabbitMQ startup failed: stage=channel error_type=%s", ("RuntimeError",), False),
    ]
    assert connection.closed_calls == 1
    assert connection.is_closed is False


class _RecordingQueue:
    def __init__(self) -> None:
        self.handler = None
        self.bound_to = None
        self.bound_routing_key = None

    async def bind(self, exchange, routing_key) -> None:
        self.bound_to = exchange
        self.bound_routing_key = routing_key

    async def consume(self, handler) -> None:
        self.handler = handler


class _RecordingChannel:
    is_closed = False

    def __init__(self) -> None:
        self.declared_queue_names: list[str] = []
        self.queue = _RecordingQueue()

    async def declare_queue(self, name, **kwargs) -> _RecordingQueue:
        self.declared_queue_names.append(name)
        return self.queue


class _FakeExchange:
    async def publish(self, *args, **kwargs) -> None:
        pass


class _FakeMessage:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode("utf-8")
        self.content_type = "application/json"
        self.headers: dict = {}
        self.acked = False
        self.rejected = False

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True


async def test_consume_direct_never_logs_the_queue_name_across_a_message_cycle(
    caplog,
) -> None:
    """Driving ``consume()`` directly with a sentinel queue name, then
    running one full message cycle (received -> callback -> acked) through
    the registered handler, must never place the queue name in any emitted
    record."""
    adapter = _adapter()
    channel = _RecordingChannel()
    adapter._channel = channel
    adapter._exchange = _FakeExchange()

    handled = []

    async def callback(body: dict) -> None:
        handled.append(body)

    caplog.set_level(logging.DEBUG)
    await adapter.consume(QUEUE_SENTINEL, callback)

    assert channel.declared_queue_names == [QUEUE_SENTINEL]
    assert channel.queue.bound_routing_key == QUEUE_SENTINEL
    assert channel.queue.handler is not None

    message = _FakeMessage({"ok": True})
    await channel.queue.handler(message)

    assert handled == [{"ok": True}]
    assert message.acked is True
    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert QUEUE_SENTINEL not in rendered


async def test_consume_with_message_direct_never_logs_the_queue_name_across_a_message_cycle(
    caplog,
) -> None:
    """Same control for ``consume_with_message()``, whose callback owns
    ack/reject directly."""
    adapter = _adapter()
    channel = _RecordingChannel()
    adapter._channel = channel
    adapter._exchange = _FakeExchange()

    handled = []

    async def callback(body: dict, message) -> None:
        handled.append(body)
        await message.ack()

    caplog.set_level(logging.DEBUG)
    await adapter.consume_with_message(QUEUE_SENTINEL, callback)

    assert channel.declared_queue_names == [QUEUE_SENTINEL]
    assert channel.queue.bound_routing_key == QUEUE_SENTINEL
    assert channel.queue.handler is not None

    message = _FakeMessage({"ok": True})
    await channel.queue.handler(message)

    assert handled == [{"ok": True}]
    assert message.acked is True
    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert QUEUE_SENTINEL not in rendered


async def test_consume_with_message_callback_failure_still_omits_the_queue_name(
    caplog,
) -> None:
    """The retry/error path inside consume_with_message's on_message must
    also stay clear of the queue name when the callback raises."""
    adapter = _adapter()
    channel = _RecordingChannel()
    adapter._channel = channel
    adapter._exchange = _FakeExchange()

    async def callback(body: dict, message) -> None:
        raise RuntimeError("callback exploded")

    caplog.set_level(logging.DEBUG)
    await adapter.consume_with_message(QUEUE_SENTINEL, callback)

    message = _FakeMessage({"ok": True})
    await channel.queue.handler(message)

    assert message.rejected is True
    rendered = "\n".join(r.getMessage() for r in caplog.records)
    assert QUEUE_SENTINEL not in rendered
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert [(r.msg, r.args, r.exc_info) for r in errors] == [
        ("consume_with_message callback failed: error_type=%s", ("RuntimeError",), False),
    ]
