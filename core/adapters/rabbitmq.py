from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

import aio_pika
from aio_pika import ExchangeType, Message

logger = logging.getLogger(__name__)


class RabbitMQAdapter:
    """RabbitMQ transport adapter using aio-pika.

    Implements the TransportPort protocol for message consumption and publishing.
    Uses early ACK: messages are acknowledged after successful JSON parsing,
    before the application callback runs. Processing continues as an asyncio
    background task, decoupling pipeline duration from RabbitMQ consumer_timeout.
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
        self._tasks: set[asyncio.Task] = set()

    async def connect(self) -> None:
        """Establish connection and channel."""
        url = f"amqp://{self._user}:{self._password}@{self._host}:{self._port}/?heartbeat={self._heartbeat}"
        # Enable TCP keepalive to prevent Docker/kernel from killing idle connections
        self._connection = await aio_pika.connect_robust(
            url,
            tcp_keepalive=True,
        )
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=1)
        self._exchange = await self._channel.declare_exchange(
            self._exchange_name,
            ExchangeType.DIRECT,
            durable=True,
        )
        logger.info("Connected to RabbitMQ at %s:%d", self._host, self._port)

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

        Messages are ACKed immediately after successful JSON parsing (early ACK).
        The application callback then runs as an asyncio background task,
        decoupling processing time from RabbitMQ's consumer_timeout.

        JSON parse failures use retry-with-header logic up to max_retries,
        then reject the message.
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

            # Phase 1: Parse JSON. On failure, retry/reject (pre-ACK).
            try:
                body = json.loads(message.body.decode("utf-8"))
            except Exception as exc:
                if retry_count < max_retries - 1:
                    logger.warning(
                        "JSON parse failed (attempt %d/%d), requeuing: %s",
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
                        "JSON parse failed after %d attempts, discarding: %s",
                        max_retries, exc,
                    )
                    await message.reject(requeue=False)
                return

            # Phase 2: Early ACK — message is valid JSON, acknowledge immediately.
            logger.info(
                "Received message on queue %s (attempt %d/%d), ACKing early",
                queue, retry_count + 1, max_retries,
            )
            await message.ack()

            # Phase 3: Dispatch callback as background task.
            task = asyncio.create_task(callback(body))
            self._tasks.add(task)
            task.add_done_callback(self._task_done)

        await q.consume(on_message)
        logger.info("Consuming from queue: %s", queue)

    def _task_done(self, task: asyncio.Task) -> None:
        """Done-callback for background processing tasks.

        Removes the task from the tracking set and logs any unhandled exception.
        """
        self._tasks.discard(task)
        if task.cancelled():
            logger.warning("Background processing task was cancelled")
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Unhandled exception in background processing task: %s", exc,
                exc_info=exc,
            )

    async def drain(self, timeout: float = 30.0) -> None:
        """Wait for all in-flight processing tasks to complete.

        Args:
            timeout: Maximum seconds to wait. After expiry, remaining tasks
                     are cancelled.
        """
        if not self._tasks:
            logger.info("No in-flight tasks to drain")
            return

        logger.info("Draining %d in-flight task(s) (timeout=%.1fs)", len(self._tasks), timeout)
        tasks = list(self._tasks)
        done, pending = await asyncio.wait(tasks, timeout=timeout)

        if pending:
            logger.warning(
                "Drain timeout: cancelling %d remaining task(s)", len(pending),
            )
            for task in pending:
                task.cancel()
            # Wait briefly for cancellation to propagate
            await asyncio.wait(pending, timeout=5.0)

        logger.info("Drain complete: %d done, %d cancelled", len(done), len(pending))

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

    async def close(self) -> None:
        """Close the connection."""
        if self._connection and not self._connection.is_closed:
            await self._connection.close()
            logger.info("RabbitMQ connection closed")
