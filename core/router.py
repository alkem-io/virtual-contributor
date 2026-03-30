from __future__ import annotations

import logging
from typing import Any

from core.events.ingest_space import IngestBodyOfKnowledge
from core.events.ingest_website import IngestWebsite
from core.events.input import Input

logger = logging.getLogger(__name__)


class RouterError(Exception):
    pass


class Router:
    """Content-based message router.

    Routes incoming RabbitMQ messages to the correct event model
    based on message content and plugin type configuration.
    """

    def __init__(self, plugin_type: str) -> None:
        self._plugin_type = plugin_type

    def parse_event(self, body: dict[str, Any]) -> Input | IngestWebsite | IngestBodyOfKnowledge:
        """Parse a raw message body into the appropriate event model."""
        try:
            if body.get("eventType") == "IngestWebsite":
                return IngestWebsite.model_validate(body)

            if self._plugin_type == "ingest-space":
                return IngestBodyOfKnowledge.model_validate(body)

            input_data = body.get("input")
            if input_data is None:
                raise RouterError("Message body missing 'input' key for engine query")
            return Input.model_validate(input_data)
        except Exception as exc:
            raise RouterError(f"Failed to parse message: {exc}") from exc

    def build_response_envelope(self, response: Any, original_event: Any) -> dict[str, Any]:
        """Wrap a response in the published envelope format.

        Engine queries: {"response": {...}, "original": {...}}
        Ingest events: {"response": {...}}
        """
        envelope: dict[str, Any] = {"response": response.model_dump()}
        if isinstance(original_event, Input):
            envelope["original"] = original_event.model_dump()
        return envelope
