"""Unit tests for GuidancePlugin."""

from __future__ import annotations

import pytest

from core.domain.retrieval_filters import FACTUAL_WHERE
from core.events.response import Response
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
        assert all(call[3] == FACTUAL_WHERE for call in plugin._knowledge_store.query_calls)

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
            async def query(self, collection, query_texts, n_results=10, where=None):
                self.query_calls.append((collection, query_texts, n_results, where))
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

    async def test_source_prefix_formatting(self, plugin):
        """Context passed to LLM should have [source:N] prefixes."""
        event = make_input()
        await plugin.handle(event)
        # The LLM call should contain [source:0] in the prompt
        llm_prompt = plugin._llm.calls[-1][0]["content"]
        assert "[source:0]" in llm_prompt

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
            async def query(self, collection, query_texts, n_results=10, where=None):
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

    async def test_factual_filter_returns_only_chunks_from_each_collection(self):
        store = MockKnowledgeStorePort()
        for collection in [
            "alkem.io-knowledge",
            "welcome.alkem.io-knowledge",
            "www.alkemio.org-knowledge",
        ]:
            await store.ingest(
                collection,
                ["chunk content", "summary content", "legacy chunk"],
                [
                    {"embeddingType": "chunk", "type": "knowledge", "source": f"{collection}/chunk"},
                    {"embeddingType": "summary", "type": "knowledge", "source": f"{collection}/summary"},
                    {"type": "knowledge", "source": f"{collection}/legacy"},
                ],
                [f"{collection}-chunk", f"{collection}-summary", f"{collection}-legacy"],
            )
        plugin = GuidancePlugin(
            llm=MockLLMPort(response='{"answer": "ok"}'), knowledge_store=store, n_results=2
        )

        await plugin.handle(make_input())

        assert all(call[3] == FACTUAL_WHERE for call in store.query_calls)
        prompt = plugin._llm.calls[-1][0]["content"]
        assert "summary content" not in prompt
        assert "chunk content" in prompt

    async def test_legacy_and_overview_entries_partition_for_guidance_retrieval(self):
        store = MockKnowledgeStorePort()
        for collection in [
            "alkem.io-knowledge",
            "welcome.alkem.io-knowledge",
            "www.alkemio.org-knowledge",
        ]:
            await store.ingest(
                collection,
                [
                    "E1 chunk",
                    "E2 summary",
                    "E3 overview",
                    "E4 chunk",
                    "E5 summary",
                    "E6 overview",
                    "E7 overview",
                    "E8 legacy",
                    "E9 old overview",
                ],
                [
                    {"embeddingType": "chunk", "type": "knowledge", "source": f"{collection}/e1"},
                    {"embeddingType": "summary", "type": "knowledge", "source": f"{collection}/e2"},
                    {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary", "source": f"{collection}/e3"},
                    {"embeddingType": "chunk", "type": "knowledge", "source": f"{collection}/e4"},
                    {"embeddingType": "summary", "type": "knowledge", "source": f"{collection}/e5"},
                    {"type": "bodyOfKnowledgeSummary", "source": f"{collection}/e6"},
                    {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary", "source": f"{collection}/e7"},
                    {"type": "knowledge", "source": f"{collection}/e8"},
                    {"type": "bodyOfKnowledgeSummary", "source": f"{collection}/e9"},
                ],
                [f"{collection}-e{i}" for i in range(1, 10)],
            )
        plugin = GuidancePlugin(llm=MockLLMPort(), knowledge_store=store, n_results=9)

        await plugin.handle(make_input())

        prompt = plugin._llm.calls[-1][0]["content"]
        assert all(entry in prompt for entry in ["E1 chunk", "E4 chunk", "E8 legacy"])
        assert all(
            entry not in prompt
            for entry in [
                "E2 summary",
                "E3 overview",
                "E5 summary",
                "E6 overview",
                "E7 overview",
                "E9 old overview",
            ]
        )

    async def test_only_summaries_produce_no_relevant_context_for_guidance(self, caplog):
        store = MockKnowledgeStorePort()
        for collection in [
            "alkem.io-knowledge",
            "welcome.alkem.io-knowledge",
            "www.alkemio.org-knowledge",
        ]:
            await store.ingest(
                collection,
                ["document summary", "overview"],
                [
                    {"embeddingType": "summary", "type": "knowledge"},
                    {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary"},
                ],
                [f"{collection}-summary", f"{collection}-overview"],
            )
        plugin = GuidancePlugin(llm=MockLLMPort(), knowledge_store=store)

        import logging

        with caplog.at_level(logging.WARNING):
            result = await plugin.handle(make_input())

        assert result.result == "Mock LLM response"
        assert "No relevant context found." in plugin._llm.calls[-1][0]["content"]
        # Positive discriminators (CQ-1): the queries genuinely ran with the
        # factual filter AND none was swallowed as a failure — asserting on
        # the failure log is what actually differs between "correctly
        # filtered everything out" and "every query threw and was swallowed".
        assert len(store.query_calls) == 3
        assert all(call[3] == FACTUAL_WHERE for call in store.query_calls)
        assert "Failed to query collection" not in caplog.text
        # ...and the summary/overview content never reached the prompt:
        prompt = plugin._llm.calls[-1][0]["content"]
        assert "document summary" not in prompt
