"""Unit tests for GuidancePlugin."""

from __future__ import annotations

import pytest

from core.events.response import Response
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockLLMPort, MockKnowledgeStorePort, make_input


class TestGuidancePlugin:
    @pytest.fixture
    def plugin(self):
        return GuidancePlugin(
            llm=MockLLMPort(response="Guidance answer"),
            knowledge_store=MockKnowledgeStorePort(),
        )

    async def test_multi_collection_query(self, plugin):
        event = make_input()
        await plugin.handle(event)
        # Should query 3 default collections
        assert len(plugin._knowledge_store.query_calls) == 3

    async def test_relevance_score_filtering(self, plugin):
        """Documents with score >= 0.3 should be included."""
        event = make_input()
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        # MockKnowledgeStore returns distances [0.1, 0.2] -> scores [0.9, 0.8]
        assert len(result.sources) > 0

    async def test_history_condensation(self, plugin):
        event = make_input(
            history=[
                {"content": "What is X?", "role": "human"},
                {"content": "X is...", "role": "assistant"},
            ],
        )
        await plugin.handle(event)
        # 1 condenser call + 1 retrieval call = 2 LLM calls
        assert len(plugin._llm.calls) == 2

    async def test_no_history_skips_condensation(self, plugin):
        event = make_input()
        await plugin.handle(event)
        # Only 1 LLM call (no condenser)
        assert len(plugin._llm.calls) == 1

    async def test_json_response_parsing(self):
        json_response = '{"answer": "Parsed answer", "sources": []}'
        plugin = GuidancePlugin(
            llm=MockLLMPort(response=json_response),
            knowledge_store=MockKnowledgeStorePort(),
        )
        event = make_input()
        result = await plugin.handle(event)
        assert result.result == "Parsed answer"

    async def test_empty_collection_handling(self):
        """Plugin should handle failed collection queries gracefully."""
        class FailingKS:
            query_calls = []
            async def query(self, collection, query_texts, n_results=10):
                raise ConnectionError("Collection unavailable")
            async def ingest(self, *a, **k): pass
            async def delete_collection(self, *a): pass

        plugin = GuidancePlugin(
            llm=MockLLMPort(response="Fallback"),
            knowledge_store=FailingKS(),
        )
        event = make_input()
        result = await plugin.handle(event)
        # Should still return a response (graceful degradation)
        assert isinstance(result, Response)

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()
