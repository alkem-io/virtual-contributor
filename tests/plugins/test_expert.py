"""Unit tests for ExpertPlugin."""

from __future__ import annotations

import pytest

from core.domain.retrieval_filters import FACTUAL_WHERE
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
        collection, _, n_results, where = plugin._knowledge_store.query_calls[0]
        assert collection == "bok-123-knowledge"
        assert n_results == 5
        assert where == FACTUAL_WHERE

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
        collection, _, _, _ = plugin._knowledge_store.query_calls[0]
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
            async def query(self, collection, query_texts, n_results=10, where=None):
                self.query_calls.append((collection, query_texts, n_results, where))
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

    async def test_factual_filter_spends_retrieval_budget_on_chunks(self):
        store = MockKnowledgeStorePort()
        await store.ingest(
            "bok-123-knowledge",
            ["chunk one", "summary", "legacy chunk", "chunk two"],
            [
                {"embeddingType": "chunk", "type": "knowledge", "source": "one"},
                {"embeddingType": "summary", "type": "knowledge", "source": "summary"},
                {"type": "knowledge", "source": "legacy"},
                {"embeddingType": "chunk", "type": "knowledge", "source": "two"},
            ],
            ["chunk-1", "summary-1", "legacy-1", "chunk-2"],
        )
        plugin = ExpertPlugin(
            llm=MockLLMPort(response="Expert answer"), knowledge_store=store, n_results=3
        )

        await plugin.handle(make_input(bodyOfKnowledgeID="bok-123"))

        assert store.query_calls[0][3] == FACTUAL_WHERE
        prompt = plugin._llm.calls[-1][0]["content"]
        assert "summary" not in prompt
        assert all(doc in prompt for doc in ["chunk one", "legacy chunk", "chunk two"])

    async def test_legacy_and_overview_entries_partition_for_expert_retrieval(self):
        store = MockKnowledgeStorePort()
        await store.ingest(
            "bok-123-knowledge",
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
                {"embeddingType": "chunk", "type": "knowledge"},
                {"embeddingType": "summary", "type": "knowledge"},
                {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary"},
                {"embeddingType": "chunk", "type": "knowledge"},
                {"embeddingType": "summary", "type": "knowledge"},
                {"type": "bodyOfKnowledgeSummary"},
                {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary"},
                {"type": "knowledge"},
                {"type": "bodyOfKnowledgeSummary"},
            ],
            [f"e{i}" for i in range(1, 10)],
        )
        plugin = ExpertPlugin(llm=MockLLMPort(), knowledge_store=store, n_results=5)

        await plugin.handle(make_input(bodyOfKnowledgeID="bok-123"))

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

    async def test_only_summaries_yield_empty_context_without_error_for_expert(self):
        """FR-010: a fully-filtered retrieval degrades gracefully — no exception,
        the summaries never reach the prompt, and the query provably ran filtered."""
        store = MockKnowledgeStorePort()
        await store.ingest(
            "bok-123-knowledge",
            ["document summary", "overview"],
            [
                {"embeddingType": "summary", "type": "knowledge"},
                {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary"},
            ],
            ["summary", "overview"],
        )
        plugin = ExpertPlugin(llm=MockLLMPort(), knowledge_store=store)

        result = await plugin.handle(make_input(bodyOfKnowledgeID="bok-123"))

        assert result.result == "Mock LLM response"
        # The retrieval genuinely executed with the factual filter:
        assert store.query_calls and store.query_calls[-1][3] == FACTUAL_WHERE
        # ...and none of the summary content leaked into the LLM prompt:
        prompt = plugin._llm.calls[-1][0]["content"]
        assert "document summary" not in prompt
        assert "overview" not in prompt

    async def test_startup_shutdown(self, plugin):
        await plugin.startup()
        await plugin.shutdown()

    async def test_handle_with_graph_populates_conversation(self):
        from unittest.mock import AsyncMock, patch, MagicMock

        captured_state = {}

        async def fake_invoke(initial_state):
            captured_state.update(initial_state)
            return {
                "final_answer": "Graph answer",
                "result_language": "EN",
            }

        mock_graph = MagicMock()
        mock_graph.compile = MagicMock(return_value=mock_graph)
        mock_graph.invoke = AsyncMock(side_effect=fake_invoke)

        with patch(
            "core.domain.prompt_graph.PromptGraph"
        ) as MockPromptGraph:
            MockPromptGraph.from_definition.return_value = mock_graph

            plugin = ExpertPlugin(
                llm=MockLLMPort(response="ignored"),
                knowledge_store=MockKnowledgeStorePort(),
            )
            event = make_input(
                bodyOfKnowledgeID="bok-1",
                promptGraph={
                    "nodes": [{"name": "n1"}],
                    "edges": [{"from": "START", "to": "END"}],
                },
                history=[
                    {"content": "Hi there", "role": "human"},
                    {"content": "Hello!", "role": "assistant"},
                ],
            )
            result = await plugin.handle(event)

        # Verify the graph was compiled with a retrieve special node
        mock_graph.compile.assert_called_once()
        compile_kwargs = mock_graph.compile.call_args
        assert "retrieve" in compile_kwargs.kwargs.get(
            "special_nodes", compile_kwargs[1].get("special_nodes", {})
        )

        # Verify initial_state has populated messages and conversation
        assert "messages" in captured_state
        assert len(captured_state["messages"]) == 3  # 2 history + 1 current
        assert captured_state["messages"][0]["role"] == "human"
        assert captured_state["messages"][0]["content"] == "Hi there"
        assert captured_state["messages"][1]["role"] == "assistant"
        assert captured_state["messages"][1]["content"] == "Hello!"
        assert captured_state["messages"][2]["role"] == "human"
        assert captured_state["messages"][2]["content"] == "What is Alkemio?"

        # Verify conversation is a formatted string
        assert "conversation" in captured_state
        assert "human:\nHi there" in captured_state["conversation"]
        assert "assistant:\nHello!" in captured_state["conversation"]

        # Verify current_question is the event message
        assert captured_state["current_question"] == "What is Alkemio?"

        # Verify the final response used the graph answer
        assert result.result == "Graph answer"

    async def test_graph_retrieval_uses_the_factual_filter(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        retrieve_node = None

        async def fake_invoke(_initial_state):
            assert retrieve_node is not None
            await retrieve_node({"current_question": "A question"})
            return {"final_answer": "Graph answer"}

        mock_graph = MagicMock()
        def capture_retrieve(*_args, **kwargs):
            nonlocal retrieve_node
            retrieve_node = kwargs["special_nodes"]["retrieve"]
            return mock_graph

        mock_graph.compile = MagicMock(side_effect=capture_retrieve)
        mock_graph.invoke = AsyncMock(side_effect=fake_invoke)

        with patch("core.domain.prompt_graph.PromptGraph") as prompt_graph:
            prompt_graph.from_definition.return_value = mock_graph
            store = MockKnowledgeStorePort()
            plugin = ExpertPlugin(llm=MockLLMPort(), knowledge_store=store)
            event = make_input(
                promptGraph={
                    "nodes": [{"name": "n1"}],
                    "edges": [{"from": "START", "to": "END"}],
                }
            )
            await plugin.handle(event)

        assert store.query_calls[0][3] == FACTUAL_WHERE
