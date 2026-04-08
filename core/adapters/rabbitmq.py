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

    Supports **early ACK** mode: when ``pipeline_timeout`` is passed to
    ``consume()``, messages are acknowledged immediately after JSON parsing
    succeeds, and the callback runs asynchronously as a background task
    wrapped in ``asyncio.wait_for()``.  This prevents RabbitMQ
    ``consumer_timeout`` from killing long-running pipelines.
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
        self._inflight_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]

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

    async def consume(
        self,
        queue: str,
        callback: Callable,
        pipeline_timeout: float | None = None,
    ) -> None:
        """Start consuming messages from a queue.

        When *pipeline_timeout* is provided the adapter operates in **early
        ACK** mode:

        1. Parse the message body as JSON.
        2. If parsing fails, NACK (``reject(requeue=False)``) and return.
        3. ACK the message immediately.
        4. Spawn *callback(body)* as a background ``asyncio.Task`` wrapped
           in ``asyncio.wait_for(timeout=pipeline_timeout)``.

        When *pipeline_timeout* is ``None`` the legacy behaviour is used
        (callback runs inline, no early ACK -- useful for tests).
        """
        if self._channel is None or self._exchange is None:
            raise RuntimeError("Not connected to RabbitMQ")

        q = await self._channel.declare_queue(
            queue, durable=True, auto_delete=False,
        )
        await q.bind(self._exchange, routing_key=queue)

        inflight = self._inflight_tasks
        timeout = pipeline_timeout

        async def _run_callback(body: dict, queue_name: str) -> None:
            """Execute the callback with an optional outer timeout."""
            try:
                if timeout and timeout > 0:
                    await asyncio.wait_for(callback(body), timeout=timeout)
                else:
                    await callback(body)
            except asyncio.TimeoutError:
                logger.error(
                    "Pipeline timeout (%.0fs) exceeded for message on queue %s",
                    timeout,
                    queue_name,
                )
            except Exception as exc:
                # Callback should handle its own errors, but guard against
                # unexpected leakage so the consumer loop keeps running.
                logger.exception(
                    "Unhandled exception in background task for queue %s: %s",
                    queue_name,
                    exc,
                )

        async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            # --- Step 1: Parse JSON ------------------------------------------------
            try:
                body = json.loads(message.body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.error(
                    "Invalid message body on queue %s, rejecting: %s", queue, exc,
                )
                await message.reject(requeue=False)
                return

            # --- Step 2: Early ACK -------------------------------------------------
            logger.info("Received message on queue %s — ACK'd early", queue)
            await message.ack()

            # --- Step 3: Dispatch callback as background task ----------------------
            task = asyncio.create_task(_run_callback(body, queue))
            inflight.add(task)
            task.add_done_callback(inflight.discard)

        await q.consume(on_message)
        logger.info("Consuming from queue: %s (pipeline_timeout=%s)", queue, timeout)

    async def drain_tasks(self, timeout: float = 30.0) -> None:
        """Wait for all in-flight background tasks to complete.

        Called during graceful shutdown. Tasks that do not finish within
        *timeout* seconds are cancelled.
        """
        pending = list(self._inflight_tasks)
        if not pending:
            logger.info("No in-flight tasks to drain")
            return

        logger.info("Draining %d in-flight task(s) (timeout=%.0fs)", len(pending), timeout)
        done, not_done = await asyncio.wait(pending, timeout=timeout)

        if not_done:
            logger.warning(
                "%d task(s) did not complete within %.0fs — cancelling",
                len(not_done),
                timeout,
            )
            for t in not_done:
                t.cancel()
            # Allow cancellation to propagate
            await asyncio.gather(*not_done, return_exceptions=True)

        logger.info("Task drain complete: %d finished, %d cancelled", len(done), len(not_done))

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
