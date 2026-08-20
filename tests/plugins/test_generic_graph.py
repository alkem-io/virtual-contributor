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
        manipulating state either.

        The poisoning node is itself a `retrieve` node whose `output_key` is
        `bok_id` — an `echo` node can only ever write to `result` (its
        output key is hardcoded in `_make_echo_node`), so it can never
        actually overwrite `bok_id` and would make this assertion pass
        whether or not the plugin's scoping exists at all. This shape
        overwrites the real `bok_id` *state* value, so the test only passes
        if the plugin genuinely ignores it."""
        llm = MockLLMPort(response="unused")
        store = MockKnowledgeStorePort()
        # Both queries the fixed plugin ever issues land on the caller's own
        # collection — seeded with a document whose text IS the string
        # "victim-space", so the poison node's retrieved value becomes that
        # literal string once written into `bok_id` state.
        store.collections["ls-101-knowledge"] = [
            {"document": "victim-space", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        # Never legitimately queried; its presence is what a scoping defect
        # would redirect the second query to.
        store.collections["victim-space-knowledge"] = [
            {"document": "victim-doc", "metadata": {"embeddingType": "chunk"}, "id": "2"},
        ]
        plugin = GenericPlugin(llm=llm, knowledge_store=store)
        graph = _retrieve_graph()
        graph["nodes"].insert(0, {
            "name": "poison",
            "type": "retrieve",
            "collection_template": "{bok_id}-knowledge",
            "query_template": "about {current_question}",
            "n_results": 1,
            "output_key": "bok_id",
        })
        graph["edges"].insert(0, {"from": "START", "to": "poison"})
        graph["edges"][1] = {"from": "poison", "to": "load"}
        event = make_input(
            promptGraph=graph,
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        # Both the poison node's own query and the downstream `load` node's
        # query must land on the caller's real collection — never on
        # "victim-space-knowledge", regardless of what `bok_id` state holds
        # by the time `load` runs.
        assert len(store.query_calls) == 2
        collections = [call[0] for call in store.query_calls]
        assert collections == ["ls-101-knowledge", "ls-101-knowledge"]

    async def test_store_present_but_embeddings_unusable_raises_before_any_llm_call(self):
        """A knowledge store that is configured but was built with no
        embeddings provider (the docker-compose default: `VECTOR_DB_HOST`
        set, `EMBEDDINGS_API_KEY`/`EMBEDDINGS_ENDPOINT` empty) previously
        passed the presence-only gate and failed late, inside the store
        itself, after paid LLM calls already ran. The capability must be
        checked before any node runs."""
        from core.domain.prompt_graph import PromptGraphConfigError

        class StoreWithNoEmbeddings:
            """Shape-mirrors ChromaDBAdapter(embeddings=None): present, but
            unable to embed a query."""
            _embeddings = None

            async def query(self, *args, **kwargs):
                raise AssertionError("store must not be queried — capability gate should fail first")

        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm, knowledge_store=StoreWithNoEmbeddings())
        event = make_input(promptGraph=_retrieve_graph(), bodyOfKnowledgeID="ls-101")
        with pytest.raises(PromptGraphConfigError, match="embeddings"):
            await plugin.handle(event)
        assert llm.calls == []

    async def test_retrieve_node_with_no_bok_id_raises_before_any_llm_call(self):
        """A retrieve-bearing payload with an empty `bodyOfKnowledgeID`
        previously fell back to a shared `default-knowledge` collection —
        pooling every BoK-less persona's retrieval into one collection. Must
        fail loudly, naming the missing field, before any node runs or any
        collection name is even constructed."""
        from core.domain.prompt_graph import PromptGraphConfigError

        llm = MockLLMPort(response="unused")
        store = MockKnowledgeStorePort()
        plugin = GenericPlugin(llm=llm, knowledge_store=store)
        event = make_input(promptGraph=_retrieve_graph(), bodyOfKnowledgeID="")
        with pytest.raises(PromptGraphConfigError, match="bodyOfKnowledgeID"):
            await plugin.handle(event)
        assert llm.calls == []
        assert store.query_calls == []

    async def test_malformed_node_entry_raises_named_config_error_no_store(self):
        """A bare string in `nodes` (instead of a dict) previously produced
        a named `PromptGraphConfigError` from `from_definition`'s own
        `"name" not in node_def` guard. Hoisting `has_retrieve_node` to scan
        the raw payload unconditionally (for the tenancy/embeddings
        pre-checks) must stay defensive against exactly this malformed
        shape — a `.get()` call on a plain string raises `AttributeError`
        instead, losing the construct-naming guarantee (SC-004). Must still
        surface a named `PromptGraphConfigError`, not an `AttributeError`."""
        from core.domain.prompt_graph import PromptGraphConfigError

        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm, knowledge_store=None)
        event = make_input(
            promptGraph={
                "nodes": ["load"],
                "edges": [{"from": "START", "to": "load"}, {"from": "load", "to": "END"}],
                "state": {"type": "object", "properties": {}},
            },
        )
        with pytest.raises(PromptGraphConfigError, match="load") as excinfo:
            await plugin.handle(event)
        assert not isinstance(excinfo.value, AttributeError)

    async def test_malformed_node_entry_raises_named_config_error_with_store(self):
        """Same malformed shape, but with a knowledge store configured —
        the hoisted scan runs inside the `if self._knowledge_store is not
        None` branch's sibling checks too, so both configurations must fall
        through to `from_definition`'s named rejection rather than raising
        `AttributeError` from the retrieve-node scan itself."""
        from core.domain.prompt_graph import PromptGraphConfigError

        llm = MockLLMPort(response="unused")
        store = MockKnowledgeStorePort()
        plugin = GenericPlugin(llm=llm, knowledge_store=store)
        event = make_input(
            promptGraph={
                "nodes": ["load"],
                "edges": [{"from": "START", "to": "load"}, {"from": "load", "to": "END"}],
                "state": {"type": "object", "properties": {}},
            },
            bodyOfKnowledgeID="ls-101",
        )
        with pytest.raises(PromptGraphConfigError, match="load") as excinfo:
            await plugin.handle(event)
        assert not isinstance(excinfo.value, AttributeError)
        assert store.query_calls == []

    async def test_no_retrieve_node_still_works_without_bok_id(self):
        """Regression guard: a graph with no retrieve node has nothing to
        scope, so an absent `bodyOfKnowledgeID` must not be affected by the
        new guard — this is exactly `test_graph_path_taken_when_payload_present_no_condensation`'s
        setup, re-asserted here to pin the "unaffected" half of the fix."""
        llm = MockLLMPort(response="unused")
        plugin = GenericPlugin(llm=llm)
        event = make_input(promptGraph=_echo_graph(), bodyOfKnowledgeID="")
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == event.message

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
