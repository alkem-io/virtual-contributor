"""Minimal echo plugin — validates extensibility with zero core changes."""

from __future__ import annotations

from core.events.input import Input
from core.events.response import Response


class EchoPlugin:
    """Echo plugin: returns the input message as the response."""

    name = "echo"
    event_type = Input

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def handle(self, event: Input, **ports) -> Response:
        return Response(result=event.message)
