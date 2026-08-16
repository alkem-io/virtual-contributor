from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from contextlib import contextmanager
from collections.abc import Awaitable, Callable

import aio_pika
from aio_pika import ExchangeType, Message

logger = logging.getLogger(__name__)


_connection_diagnostic_suppressed: ContextVar[bool] = ContextVar(
    "rabbitmq_connection_diagnostic_suppressed", default=False,
)

# Both locked dependencies derive every module/child logger from these two
# base names (``aio_pika.log.get_logger`` and aiormq's per-module
# ``getLogger(__name__)`` calls, including dynamic ``.getChild(...)``
# children such as ``aiormq.connection.marshall``). Matching by dot-boundary
# prefix at the point every propagated record is actually observed catches
# all of them, present and future, unlike an enumerated leaf-logger list.
_SUPPRESSED_DEPENDENCY_LOGGER_PREFIXES = ("aio_pika", "aiormq")


def _is_suppressed_dependency_logger(name: str) -> bool:
    return any(
        name == prefix or name.startswith(f"{prefix}.")
        for prefix in _SUPPRESSED_DEPENDENCY_LOGGER_PREFIXES
    )


# Logger-level filters only run for the logger a record was logged through,
# not for its ancestors — so a filter attached to ``aiormq.connection``
# never sees a record from its dynamically created ``.marshall`` child.
# ``Handler.filter`` runs once per handler on every record that reaches it
# after propagation, regardless of which logger originated it, which is the
# layer that can actually enforce this boundary completely. Patched once at
# import time; there is exactly one handler installed for this process
# (``core.logging.setup_logging``).
_stdlib_handler_filter = logging.Handler.filter


def _connection_diagnostic_handler_filter(
    self: logging.Handler, record: logging.LogRecord,
) -> bool:
    if _connection_diagnostic_suppressed.get() and _is_suppressed_dependency_logger(record.name):
        return False
    # logging.Handler.filter always returns a plain bool at runtime; the
    # typeshed stub widens it via Filterer.filter's overload, so pin the
    # narrowed type explicitly rather than let the unbound-method call widen it.
    return bool(_stdlib_handler_filter(self, record))


logging.Handler.filter = _connection_diagnostic_handler_filter  # type: ignore[method-assign]


@contextmanager
def _suppress_connection_dependency_diagnostics():
    """Keep connection/reconnect details out of this startup task's logs."""
    token = _connection_diagnostic_suppressed.set(True)
    try:
        yield
    finally:
        _connection_diagnostic_suppressed.reset(token)


class RabbitMQAdapter:
    """RabbitMQ transport adapter using aio-pika.

    Implements the TransportPort protocol for message consumption and publishing.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        exchange_name: str,
        heartbeat: int = 300,
        max_retries: int = 3,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._exchange_name = exchange_name
        self._heartbeat = heartbeat
        self._max_retries = max_retries
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        """Establish connection and channel.

        The suppression boundary and the static-exception projection span the
        complete handshake — connection, channel creation, QoS, and exchange
        declaration — not just the initial connect. A failure at any stage
        after the connection is open closes that connection inside the same
        boundary before the sanitized failure is raised.
        """
        url = f"amqp://{self._user}:{self._password}@{self._host}:{self._port}/?heartbeat={self._heartbeat}"
        # Enable TCP keepalive to prevent Docker/kernel from killing idle connections
        with _suppress_connection_dependency_diagnostics():
            try:
                connection = await aio_pika.connect_robust(url, tcp_keepalive=True)
            except Exception as exc:
                logger.error(
                    "RabbitMQ startup failed: stage=connect error_type=%s",
                    type(exc).__name__,
                    exc_info=False,
                )
                raise RuntimeError("RabbitMQ startup failed") from None

            try:
                channel = await connection.channel()
            except Exception as exc:
                await self._close_after_stage_failure(connection)
                logger.error(
                    "RabbitMQ startup failed: stage=channel error_type=%s",
                    type(exc).__name__,
                    exc_info=False,
                )
                raise RuntimeError("RabbitMQ startup failed") from None

            try:
                await channel.set_qos(prefetch_count=1)
            except Exception as exc:
                await self._close_after_stage_failure(connection)
                logger.error(
                    "RabbitMQ startup failed: stage=qos error_type=%s",
                    type(exc).__name__,
                    exc_info=False,
                )
                raise RuntimeError("RabbitMQ startup failed") from None

            try:
                exchange = await channel.declare_exchange(
                    self._exchange_name,
                    ExchangeType.DIRECT,
                    durable=True,
                )
            except Exception as exc:
                await self._close_after_stage_failure(connection)
                logger.error(
                    "RabbitMQ startup failed: stage=exchange error_type=%s",
                    type(exc).__name__,
                    exc_info=False,
                )
                raise RuntimeError("RabbitMQ startup failed") from None

        self._connection = connection
        self._channel = channel
        self._exchange = exchange
        logger.info("Connected to RabbitMQ")

    @staticmethod
    async def _close_after_stage_failure(
        connection: aio_pika.abc.AbstractRobustConnection,
    ) -> None:
        """Close an already-opened connection after a later stage fails.

        Cleanup itself must not leak a sanitized-boundary violation: any
        exception raised while closing is caught and projected through the
        same static, sentinel-free vocabulary as the stage failure it
        followed.
        """
        try:
            if not connection.is_closed:
                await connection.close()
        except Exception as cleanup_exc:
            logger.error(
                "RabbitMQ startup cleanup failed: error_type=%s",
                type(cleanup_exc).__name__,
                exc_info=False,
            )

    def is_connected(self) -> bool:
        """Check if the connection is alive."""
        return (
            self._connection is not None
            and not self._connection.is_closed
            and self._channel is not None
            and not self._channel.is_closed
        )

    async def consume(self, queue: str, callback: Callable) -> None:
        """Start consuming messages from a queue.

        The callback receives the parsed JSON body as a dict.
        Exceptions from the callback escape the process() context so
        aio-pika rejects/requeues the message (dead-letter on repeated failure).
        """
        if self._channel is None or self._exchange is None:
            raise RuntimeError("Not connected to RabbitMQ")

        q = await self._channel.declare_queue(
            queue, durable=True, auto_delete=False,
        )
        await q.bind(self._exchange, routing_key=queue)

        max_retries = self._max_retries
        exchange = self._exchange
        assert exchange is not None, "consume() called before connect()"

        async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            headers = message.headers or {}
            retry_count = int(headers.get("x-retry-count", 0))

            try:
                body = json.loads(message.body.decode("utf-8"))
                logger.info("Received message (attempt %d/%d)", retry_count + 1, max_retries)
                await callback(body)
                await message.ack()
            except Exception as exc:
                if retry_count < max_retries - 1:
                    logger.warning(
                        "Message failed (attempt %d/%d), requeuing: %s",
                        retry_count + 1, max_retries, exc,
                    )
                    new_headers = dict(headers)
                    new_headers["x-retry-count"] = retry_count + 1
                    retry_msg = Message(
                        body=message.body,
                        content_type=message.content_type,
                        headers=new_headers,
                    )
                    try:
                        await exchange.publish(retry_msg, routing_key=queue)
                    except Exception as pub_exc:
                        logger.error("Failed to republish retry message: %s", pub_exc)
                    await message.reject(requeue=False)
                else:
                    logger.error(
                        "Message failed after %d attempts, discarding: %s",
                        max_retries, exc,
                    )
                    await message.reject(requeue=False)

        await q.consume(on_message)
        logger.info("Consuming from queue")

    async def consume_with_message(
        self,
        queue: str,
        callback: Callable[[dict, aio_pika.abc.AbstractIncomingMessage], Awaitable[None]],
    ) -> None:
        """Start consuming, passing both parsed body and raw message to callback.

        Unlike ``consume()``, this method does NOT ACK or reject messages.
        The callback is fully responsible for the message lifecycle
        (calling ``message.ack()`` / ``message.reject()``).
        """
        if self._channel is None or self._exchange is None:
            raise RuntimeError("Not connected to RabbitMQ")

        q = await self._channel.declare_queue(
            queue, durable=True, auto_delete=False,
        )
        await q.bind(self._exchange, routing_key=queue)

        async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            try:
                body = json.loads(message.body.decode("utf-8"))
                logger.info("Received message")
                await callback(body, message)
            except Exception as exc:
                # The application callback has already made its bounded delivery
                # decision.  This is only a containment boundary: never render
                # its exception, cause, context or traceback into a broker log.
                logger.error(
                    "consume_with_message callback failed: error_type=%s",
                    type(exc).__name__,
                    exc_info=False,
                )
                # Reject without requeue to avoid infinite loops;
                # the callback should handle its own ACK/reject.
                try:
                    await message.reject(requeue=False)
                except Exception as reject_exc:
                    logger.error(
                        "consume_with_message reject failed: error_type=%s",
                        type(reject_exc).__name__,
                        exc_info=False,
                    )

        await q.consume(on_message)
        logger.info("Consuming (with message) from queue")

    async def publish(self, exchange: str, routing_key: str, message: bytes) -> None:
        """Publish a message to the exchange with the given routing key."""
        if self._channel is None:
            raise RuntimeError("Not connected to RabbitMQ")

        if self._exchange is None:
            self._exchange = await self._channel.declare_exchange(
                exchange, ExchangeType.DIRECT, durable=True,
            )

        # Ensure result queue exists and is bound to the exchange
        result_queue = await self._channel.declare_queue(
            routing_key, durable=True, auto_delete=False,
        )
        await result_queue.bind(self._exchange, routing_key=routing_key)

        msg = Message(
            body=message,
            content_type="application/json",
        )
        await self._exchange.publish(msg, routing_key=routing_key)

    async def republish_with_headers(
        self, routing_key: str, body: bytes, headers: dict,
    ) -> None:
        """Republish a message to the exchange with custom headers.

        Used by the application layer to implement retry logic when
        ``consume_with_message()`` delegates ACK/reject control to the callback.
        """
        if self._exchange is None:
            raise RuntimeError("Not connected to RabbitMQ")

        msg = Message(
            body=body,
            content_type="application/json",
            headers=headers,
        )
        await self._exchange.publish(msg, routing_key=routing_key)

    async def close(self) -> None:
        """Close the connection."""
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            logger.info("RabbitMQ connection closed")
