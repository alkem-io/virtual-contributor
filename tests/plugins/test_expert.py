"""Unit tests for ExpertPlugin."""

from __future__ import annotations

import pytest

from core.events.response import Response
from core.ports.knowledge_store import QueryResult
from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockLLMPort, MockKnowledgeStorePort, make_input


class TestExpertPlugin:
    @pytest.fixture
    def plugin(self):
        return ExpertPlugin(
            llm=MockLLMPort(response="Expert answer"),
            knowledge_store=MockKnowledgeStorePort(),
        )

    async def test_simple_rag(self, plugin):
        event = make_input(bodyOfKnowledgeID="bok-123")
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "Expert answer"

    async def test_knowledge_retrieval(self, plugin):
        event = make_input(bodyOfKnowledgeID="bok-123")
        await plugin.handle(event)
        # Should have queried the knowledge store
        assert len(plugin._knowledge_store.query_calls) == 1
        collection, _, n_results = plugin._knowledge_store.query_calls[0]
        assert collection == "bok-123-knowledge"
        assert n_results == 5

    async def test_response_has_sources(self, plugin):
        event = make_input(bodyOfKnowledgeID="bok-123")
        result = await plugin.handle(event)
        assert isinstance(result.sources, list)
        assert len(result.sources) > 0

    async def test_language_field(self, plugin):
        event = make_input(bodyOfKnowledgeID="bok-123", language="NL")
        result = await plugin.handle(event)
        assert result.human_language == "NL"

    async def test_default_collection_when_no_bok(self, plugin):
        event = make_input()
        await plugin.handle(event)
        collection, _, _ = plugin._knowledge_store.query_calls[0]
        assert collection == "default-knowledge"

    async def test_extract_sources_with_no_sources_in_state(self, plugin):
        """_extract_sources returns [] when state has no 'sources' key."""
        result = ExpertPlugin._extract_sources({})
        assert result == []

    async def test_extract_sources_with_query_result(self, plugin):
        """_extract_sources builds Source list from a QueryResult."""
        qr = QueryResult(
            documents=[["doc1"]],
            metadatas=[[{"source": "s", "title": "t", "chunkIndex": 0}]],
            distances=[[0.2]],
            ids=[["id1"]],
        )
        sources = ExpertPlugin._extract_sources({"sources": qr})
        assert len(sources) == 1
        assert sources[0].score == pytest.approx(0.8)
        assert sources[0].title == "t"

    async def test_build_sources_empty_metadatas(self, plugin):
        """_build_sources returns [] when metadatas is empty."""
        qr = QueryResult(documents=[], metadatas=[], distances=[], ids=[])
        assert ExpertPlugin._build_sources(qr) == []

    async def test_build_sources_no_distances(self, plugin):
        """_build_sources sets score=None when distances are missing."""
        qr = QueryResult(
            documents=[["doc"]],
            metadatas=[[{"source": "x"}]],
            distances=[],
            ids=[["id"]],
        )
        sources = ExpertPlugin._build_sources(qr)
        assert len(sources) == 1
        assert sources[0].score is None

    async def test_source_prefix_formatting(self, plugin):
        """Knowledge string should have [source:N] prefixes."""
        event = make_input(bodyOfKnowledgeID="bok-123")
        await plugin.handle(event)
        llm_prompt = plugin._llm.calls[-1][0]["content"]
        assert "[source:0]" in llm_prompt
        assert "[source:1]" in llm_prompt

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

        plugin = ExpertPlugin(
            llm=MockLLMPort(response="Expert answer"),
            knowledge_store=LowScoreKS(),
        )
        event = make_input(bodyOfKnowledgeID="bok-123")
        result = await plugin.handle(event)
        # Only the high-score source should survive
        assert len(result.sources) == 1
        assert result.sources[0].source == "a"

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()
