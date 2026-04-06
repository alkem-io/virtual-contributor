from __future__ import annotations

import json
import logging
from typing import Callable

import aio_pika
from aio_pika import ExchangeType, Message

logger = logging.getLogger(__name__)


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

        async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            headers = message.headers or {}
            retry_count = headers.get("x-retry-count", 0)

            try:
                async with message.process(requeue=False):
                    body = json.loads(message.body.decode("utf-8"))
                    logger.info("Received message on queue %s (attempt %d/%d)", queue, retry_count + 1, max_retries)
                    await callback(body)
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
                    await self._exchange.publish(retry_msg, routing_key=queue)
                else:
                    logger.error(
                        "Message failed after %d attempts, discarding: %s",
                        max_retries, exc,
                    )

        await q.consume(on_message)
        logger.info("Consuming from queue: %s", queue)

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
