"""Unit tests for OpenAIAssistantPlugin."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.events.response import Response
from plugins.openai_assistant.plugin import OpenAIAssistantPlugin
from plugins.openai_assistant.utils import strip_citations
from tests.conftest import make_input


class MockAssistantAdapter:
    """Mock OpenAI Assistant adapter for testing."""

    def __init__(self):
        self.threads_created = []
        self.messages_added = []

    def create_client(self, api_key):
        return MagicMock(name="mock_client")

    async def create_thread(self, client, message):
        thread = MagicMock()
        thread.id = "thread-new-123"
        self.threads_created.append(message)
        return thread

    async def get_thread(self, client, thread_id):
        thread = MagicMock()
        thread.id = thread_id
        return thread

    async def add_message(self, client, thread_id, message):
        self.messages_added.append((thread_id, message))

    async def attach_files(self, client, assistant_id):
        return []

    async def run_and_poll(self, client, thread_id, assistant_id, timeout=None):
        return "Assistant response\u30104:0\u2020source\u3011"


class TestOpenAIAssistantPlugin:
    @pytest.fixture
    def plugin(self):
        return OpenAIAssistantPlugin(openai_assistant=MockAssistantAdapter())

    async def test_thread_creation(self, plugin):
        event = make_input(
            externalConfig={"apiKey": "sk-test", "assistantId": "ast-1", "model": None},
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.thread_id == "thread-new-123"

    async def test_thread_resumption(self, plugin):
        event = make_input(
            externalConfig={"apiKey": "sk-test", "assistantId": "ast-1", "model": None},
            externalMetadata={"threadId": "thread-existing"},
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        # Should have added message to existing thread
        assert len(plugin._assistant.messages_added) == 1
        assert plugin._assistant.messages_added[0][0] == "thread-existing"

    async def test_citation_stripping(self, plugin):
        event = make_input(
            externalConfig={"apiKey": "sk-test", "assistantId": "ast-1", "model": None},
        )
        result = await plugin.handle(event)
        assert "\u3010" not in result.result
        assert "source" not in result.result

    async def test_missing_api_key(self, plugin):
        event = make_input()
        result = await plugin.handle(event)
        assert "Error" in result.result

    async def test_missing_assistant_id(self, plugin):
        event = make_input(
            externalConfig={"apiKey": "sk-test", "model": None},
        )
        result = await plugin.handle(event)
        assert "Error" in result.result


class TestStripCitations:
    def test_basic_citation(self):
        assert strip_citations("Hello\u30104:0\u2020source\u3011world") == "Helloworld"

    def test_no_citations(self):
        assert strip_citations("Hello world") == "Hello world"

    def test_multiple_citations(self):
        text = "First\u30101:0\u2020doc.pdf\u3011 then\u30102:1\u2020ref\u3011 end"
        result = strip_citations(text)
        assert "\u3010" not in result

    def test_empty_string(self):
        assert strip_citations("") == ""
