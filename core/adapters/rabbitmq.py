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
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._exchange_name = exchange_name
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        """Establish connection and channel."""
        url = f"amqp://{self._user}:{self._password}@{self._host}:{self._port}/"
        self._connection = await aio_pika.connect_robust(url)
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
        It should return a response dict or None.
        """
        if self._channel is None:
            raise RuntimeError("Not connected to RabbitMQ")

        q = await self._channel.declare_queue(
            queue, durable=True, auto_delete=False,
        )

        async def on_message(message: aio_pika.abc.AbstractIncomingMessage) -> None:
            async with message.process(requeue=True):
                try:
                    body = json.loads(message.body.decode("utf-8"))
                    logger.info("Received message on queue %s", queue)
                    await callback(body)
                except Exception:
                    logger.exception("Error processing message from queue %s", queue)
                    # Message will be requeued due to requeue=True context manager

        await q.consume(on_message)
        logger.info("Consuming from queue: %s", queue)

    async def publish(self, exchange: str, routing_key: str, message: bytes) -> None:
        """Publish a message to the exchange with the given routing key."""
        if self._channel is None:
            raise RuntimeError("Not connected to RabbitMQ")

        # Ensure result queue exists and is bound
        await self._channel.declare_queue(
            routing_key, durable=True, auto_delete=False,
        )

        if self._exchange is None:
            self._exchange = await self._channel.declare_exchange(
                exchange, ExchangeType.DIRECT, durable=True,
            )

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
