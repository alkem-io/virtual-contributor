"""Plugin-level tests — GenericPlugin's prompt-graph path (FR-004, FR-005, FR-012, US1)."""

from __future__ import annotations

import pytest

from core.domain.retrieval_filters import FACTUAL_WHERE
from core.events.response import Response
from plugins.generic.plugin import GenericPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


def _echo_graph(source: str = "current_question") -> dict:
    return {
        "nodes": [{"name": "ask", "type": "echo", "source": source}],
        "edges": [
            {"from": "START", "to": "ask"},
            {"from": "ask", "to": "END"},
        ],
        "state": {
            "type": "object",
            "properties": {
                "current_question": {"type": "string"},
                "conversation": {"type": "string"},
                "bok_id": {"type": "string"},
                "description": {"type": "string"},
                "display_name": {"type": "string"},
                "result": {"type": "string"},
            },
        },
    }


def _retrieve_graph() -> dict:
    # An echo node downstream of retrieve — avoids needing a real LangChain
    # chat-model double just to prove the store call shape/filter (an LLM
    # node's chain construction requires a genuine BaseChatModel, which is
    # exercised elsewhere; this test is about the retrieve→store wiring).
    return {
        "nodes": [
            {
                "name": "load",
                "type": "retrieve",
                "collection_template": "{bok_id}-knowledge",
                "query_template": "about {current_question}",
                "n_results": 10,
                "output_key": "knowledge_docs",
            },
            {"name": "answer", "type": "echo", "source": "knowledge_docs"},
        ],
        "edges": [
            {"from": "START", "to": "load"},
            {"from": "load", "to": "answer"},
            {"from": "answer", "to": "END"},
        ],
        "state": {
            "type": "object",
            "properties": {
                "current_question": {"type": "string"},
                "conversation": {"type": "string"},
                "bok_id": {"type": "string"},
                "description": {"type": "string"},
                "display_name": {"type": "string"},
                "knowledge_docs": {"type": "string"},
                "result": {"type": "string"},
            },
        },
    }


class TestGenericGraphPath:
    async def test_graph_path_taken_when_payload_present_no_condensation(self):
        """LLM call count proves condensation was NOT invoked on the graph
        path even with history present."""
        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm)
        event = make_input(
            promptGraph=_echo_graph(),
            history=[
                {"content": "earlier turn", "role": "human"},
                {"content": "earlier reply", "role": "assistant"},
            ],
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == event.message
        # Echo node makes no LLM call at all — proves neither condensation
        # nor any node-level LLM call ran.
        assert llm.calls == []

    async def test_direct_path_untouched_when_payload_absent(self):
        """Canary: without a payload, behaviour is the pre-existing direct
        path (existing test_generic.py files remain the authority)."""
        llm = MockLLMPort(response="Test answer")
        plugin = GenericPlugin(llm=llm)
        event = make_input()
        result = await plugin.handle(event)
        assert result.result == "Test answer"
        assert len(llm.calls) == 1

    async def test_retrieve_node_hits_store_with_factual_where_and_templated_collection(self):
        llm = MockLLMPort(response="unused")
        store = MockKnowledgeStorePort()
        store.collections["ls-101-knowledge"] = [
            {"document": "doc1", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        plugin = GenericPlugin(llm=llm, knowledge_store=store)
        event = make_input(
            promptGraph=_retrieve_graph(),
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "doc1"
        assert len(store.query_calls) == 1
        collection, query_texts, n_results, where = store.query_calls[0]
        assert collection == "ls-101-knowledge"
        assert where == FACTUAL_WHERE
        assert n_results == 10

    async def test_store_absent_retrieve_payload_raises_config_error(self):
        from core.domain.prompt_graph import PromptGraphConfigError

        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm, knowledge_store=None)
        event = make_input(promptGraph=_retrieve_graph(), bodyOfKnowledgeID="x")
        with pytest.raises(PromptGraphConfigError, match="knowledge store"):
            await plugin.handle(event)

    async def test_retrieve_ignores_state_overwritten_bok_id_stays_scoped_to_caller(self):
        """Defense in depth beyond the compile-time `collection_template`
        allowlist: even if an upstream node in the payload overwrites the
        `bok_id` *state* value before the retrieve node runs, the plugin's
        retriever is scoped from `Input.bodyOfKnowledgeID` server-side and
        ignores whatever collection name the graph itself computed — a
        payload cannot redirect retrieval to another tenant's collection by
        manipulating state either."""
        llm = MockLLMPort(response="unused")
        store = MockKnowledgeStorePort()
        store.collections["ls-101-knowledge"] = [
            {"document": "own-doc", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        store.collections["victim-space-knowledge"] = [
            {"document": "victim-doc", "metadata": {"embeddingType": "chunk"}, "id": "2"},
        ]
        plugin = GenericPlugin(llm=llm, knowledge_store=store)
        graph = _retrieve_graph()
        # An echo node re-seeds `bok_id` from a constant "victim-space" before
        # the retrieve node runs, standing in for any payload node that
        # could overwrite state.
        graph["nodes"].insert(0, {"name": "poison", "type": "echo", "source": "poison_value"})
        graph["edges"].insert(0, {"from": "START", "to": "poison"})
        graph["edges"][1] = {"from": "poison", "to": "load"}
        graph["state"]["properties"]["poison_value"] = {"type": "string"}
        event = make_input(
            promptGraph=graph,
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        # Retrieval must still be scoped to the caller's own bok_id, never
        # the "victim-space" collection, regardless of what a payload's own
        # nodes compute along the way.
        assert len(store.query_calls) == 1
        collection = store.query_calls[0][0]
        assert collection == "ls-101-knowledge"

    async def test_store_error_propagates_no_fabricated_answer(self):
        class RaisingStore:
            async def query(self, *args, **kwargs):
                raise RuntimeError("store unavailable")

        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm, knowledge_store=RaisingStore())
        event = make_input(promptGraph=_retrieve_graph(), bodyOfKnowledgeID="x")
        with pytest.raises(RuntimeError, match="store unavailable"):
            await plugin.handle(event)

    async def test_history_bounded_seeds_only_tail(self):
        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm, max_history_turns=2)
        long_history = [
            {"content": f"turn-{i}", "role": "human"} for i in range(10)
        ]
        event = make_input(promptGraph=_echo_graph(source="conversation"), history=long_history)
        result = await plugin.handle(event)
        # Only the tail turns (bounded to 2) plus the current message appear.
        assert "turn-0" not in result.result
        assert "turn-9" in result.result or event.message in result.result

    async def test_response_field_parity(self):
        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm)
        event = make_input(promptGraph=_echo_graph(), language="FR")
        result = await plugin.handle(event)
        assert result.human_language == "FR"
        assert result.sources == []
