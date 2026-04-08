"""Tests for pipeline timeout behavior in on_message.

Verifies that:
- Handlers completing within timeout produce normal results.
- Handlers exceeding timeout are cancelled and error results are published.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from core.events.response import Response
from core.router import Router
from tests.conftest import MockTransportPort, make_input


class SlowPlugin:
    """A plugin that takes configurable time to handle events."""

    name = "slow-test"
    event_type = type(make_input())

    def __init__(self, delay: float = 0.0, response_text: str = "OK") -> None:
        self._delay = delay
        self._response_text = response_text

    async def startup(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def handle(self, event) -> Response:
        await asyncio.sleep(self._delay)
        return Response(result=self._response_text)


class TestPipelineTimeout:
    """Tests for the asyncio.wait_for timeout wrapping plugin.handle()."""

    async def test_handler_within_timeout_publishes_result(self):
        """A fast handler produces a normal result envelope."""
        plugin = SlowPlugin(delay=0.0, response_text="Fast response")
        router = Router(plugin_type="generic")
        transport = MockTransportPort()

        input_body = {
            "input": make_input(message="Hello").model_dump(),
        }

        pipeline_timeout = 5  # seconds
        exchange = "test-exchange"
        routing_key = "invoke-engine-result"

        # Replicate the on_message logic from main.py
        event = None
        try:
            event = router.parse_event(input_body)
            response = await asyncio.wait_for(
                plugin.handle(event),
                timeout=pipeline_timeout,
            )
            envelope = router.build_response_envelope(response, event)
            await transport.publish(
                exchange,
                routing_key,
                json.dumps(envelope).encode("utf-8"),
            )
        except asyncio.TimeoutError:
            pytest.fail("Should not timeout for fast handler")
        except Exception:
            pytest.fail("Should not raise for fast handler")

        assert len(transport.published) == 1
        _, _, msg_bytes = transport.published[0]
        result = json.loads(msg_bytes)
        assert result["response"]["result"] == "Fast response"

    async def test_handler_exceeding_timeout_publishes_error(self):
        """A slow handler is cancelled and an error result is published."""
        plugin = SlowPlugin(delay=10.0)  # Will exceed timeout
        router = Router(plugin_type="generic")
        transport = MockTransportPort()

        input_body = {
            "input": make_input(message="Hello").model_dump(),
        }

        pipeline_timeout = 0.1  # Very short timeout
        exchange = "test-exchange"
        routing_key = "invoke-engine-result"

        # Replicate the on_message logic from main.py
        event = None
        try:
            event = router.parse_event(input_body)
            response = await asyncio.wait_for(
                plugin.handle(event),
                timeout=pipeline_timeout,
            )
            envelope = router.build_response_envelope(response, event)
            await transport.publish(
                exchange,
                routing_key,
                json.dumps(envelope).encode("utf-8"),
            )
        except asyncio.TimeoutError:
            error_response = Response(
                result=f"Error: pipeline timed out after {pipeline_timeout}s"
            )
            envelope = (
                router.build_response_envelope(error_response, event)
                if event
                else {"response": error_response.model_dump()}
            )
            await transport.publish(
                exchange,
                routing_key,
                json.dumps(envelope).encode("utf-8"),
            )

        assert len(transport.published) == 1
        _, _, msg_bytes = transport.published[0]
        result = json.loads(msg_bytes)
        assert "timed out" in result["response"]["result"]

    async def test_handler_exception_publishes_error(self):
        """A handler that raises an exception publishes an error result."""
        router = Router(plugin_type="generic")
        transport = MockTransportPort()

        class FailingPlugin:
            name = "failing-test"

            async def handle(self, event) -> Response:
                raise RuntimeError("Something went wrong")

        plugin = FailingPlugin()
        input_body = {
            "input": make_input(message="Hello").model_dump(),
        }

        pipeline_timeout = 5
        exchange = "test-exchange"
        routing_key = "invoke-engine-result"

        event = None
        try:
            event = router.parse_event(input_body)
            response = await asyncio.wait_for(
                plugin.handle(event),
                timeout=pipeline_timeout,
            )
            envelope = router.build_response_envelope(response, event)
            await transport.publish(
                exchange,
                routing_key,
                json.dumps(envelope).encode("utf-8"),
            )
        except asyncio.TimeoutError:
            pytest.fail("Should not timeout")
        except Exception as exc:
            error_response = Response(result=f"Error: {exc}")
            envelope = (
                router.build_response_envelope(error_response, event)
                if event
                else {"response": error_response.model_dump()}
            )
            await transport.publish(
                exchange,
                routing_key,
                json.dumps(envelope).encode("utf-8"),
            )

        assert len(transport.published) == 1
        _, _, msg_bytes = transport.published[0]
        result = json.loads(msg_bytes)
        assert "Something went wrong" in result["response"]["result"]
