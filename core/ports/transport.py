from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class TransportPort(Protocol):
    """Port for message transport (e.g. RabbitMQ)."""

    async def consume(self, queue: str, callback: Callable) -> None:
        """Start consuming messages from a queue."""
        ...

    async def publish(
        self, exchange: str, routing_key: str, message: bytes
    ) -> None:
        """Publish a message to an exchange with a routing key."""
        ...

    async def close(self) -> None:
        """Close the transport connection."""
        ...
