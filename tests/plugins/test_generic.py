"""Unit tests for GenericPlugin."""

from __future__ import annotations

import pytest

from core.events.input import Input, HistoryItem, MessageSenderRole
from core.events.response import Response
from plugins.generic.plugin import GenericPlugin
from tests.conftest import MockLLMPort, make_input


class TestGenericPlugin:
    @pytest.fixture
    def plugin(self):
        return GenericPlugin(llm=MockLLMPort(response="Test answer"))

    async def test_direct_llm_invoke(self, plugin):
        event = make_input(prompt=["You are helpful."])
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "Test answer"
        # Should have one call (no history condensation)
        assert len(plugin._llm.calls) == 1

    async def test_history_condensation(self, plugin):
        event = make_input(
            history=[
                {"content": "What is X?", "role": "human"},
                {"content": "X is a thing.", "role": "assistant"},
            ],
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        # Two calls: condenser + final invoke
        assert len(plugin._llm.calls) == 2

    async def test_system_message_handling(self, plugin):
        event = make_input(prompt=["System message 1", "System message 2"])
        await plugin.handle(event)
        messages = plugin._llm.calls[0]
        # Should have 2 system + 1 human
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "system"
        assert messages[2]["role"] == "human"

    async def test_no_prompt_messages(self, plugin):
        event = make_input()
        # prompt is None by default
        await plugin.handle(event)
        messages = plugin._llm.calls[0]
        assert len(messages) == 1
        assert messages[0]["role"] == "human"

    async def test_error_response_on_llm_failure(self):
        class FailingLLM:
            async def invoke(self, messages):
                raise RuntimeError("LLM unavailable")

            async def stream(self, messages):
                raise RuntimeError("LLM unavailable")

        plugin = GenericPlugin(llm=FailingLLM())
        event = make_input()
        with pytest.raises(RuntimeError, match="LLM unavailable"):
            await plugin.handle(event)

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()
