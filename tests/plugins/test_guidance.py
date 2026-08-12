"""Unit tests for GuidancePlugin."""

from __future__ import annotations

import pytest

from core.events.response import Response
from core.domain.prompts_shared import (
    render_document_block,
    rendered_document_budget_size,
)
from core.ports.knowledge_store import QueryResult
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

    async def test_low_score_chunks_filtered_out(self):
        """Chunks below the score threshold should be excluded."""
        class LowScoreKS(MockKnowledgeStorePort):
            async def query(self, collection, query_texts, n_results=10):
                self.query_calls.append((collection, query_texts, n_results))
                return QueryResult(
                    documents=[["relevant doc", "irrelevant doc"]],
                    metadatas=[[{"source": "a"}, {"source": "b"}]],
                    distances=[[0.1, 0.95]],  # scores: 0.9, 0.05
                    ids=[["id1", "id2"]],
                )

        plugin = GuidancePlugin(
            llm=MockLLMPort(response='{"answer": "ok"}'),
            knowledge_store=LowScoreKS(),
        )
        event = make_input()
        result = await plugin.handle(event)
        # Only the high-score chunk should survive filtering
        assert all(s.source == "a" for s in result.sources)

    async def test_context_budget_counts_rendered_document_labels(self):
        """Rendered labels are charged before deciding which chunks survive."""
        store = MockKnowledgeStorePort()
        for index, collection in enumerate(
            [
                "alkem.io-knowledge",
                "welcome.alkem.io-knowledge",
                "www.alkemio.org-knowledge",
            ]
        ):
            await store.ingest(
                collection,
                [chr(ord("A") + index) * 20],
                [
                    {
                        "source": f"https://example.test/{index}",
                        "embeddingType": "chunk",
                        "type": "knowledge",
                    }
                ],
                [f"id-{index}"],
            )

        first_content = "A" * 20
        first_block = render_document_block(
            1,
            first_content,
            {
                "source": "https://example.test/0",
                "embeddingType": "chunk",
                "type": "knowledge",
            },
        )
        context_budget = rendered_document_budget_size(first_block, first_content)
        plugin = GuidancePlugin(
            llm=MockLLMPort(response='{"answer": "ok"}'),
            knowledge_store=store,
            n_results=3,
            max_context_chars=context_budget,
        )

        response = await plugin.handle(make_input())
        prompt = plugin._llm.calls[-1][0]["content"]

        assert "A" * 20 in prompt
        assert "B" * 20 not in prompt
        assert "C" * 20 not in prompt
        assert len(response.sources) == 1

    async def test_source_prefix_formatting(self, plugin):
        """Context passed to LLM should have 1-based labelled document blocks."""
        event = make_input()
        await plugin.handle(event)
        llm_prompt = plugin._llm.calls[-1][0]["content"]
        assert "[Document 1 · test · origin: test]" in llm_prompt

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
