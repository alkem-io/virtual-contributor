"""Unit tests — declarative retrieve / echo nodes (FR-002, FR-003, FR-011, US1)."""

from __future__ import annotations

import pytest

from core.domain.prompt_graph import PromptGraph, PromptGraphConfigError


class FakeRetriever:
    """Records calls; returns a scripted list of document texts."""

    def __init__(self, docs: list[str] | None = None) -> None:
        self.docs = docs if docs is not None else ["doc-a", "doc-b"]
        self.calls: list[tuple[str, str, int]] = []

    async def __call__(self, collection: str, query: str, n_results: int) -> list[str]:
        self.calls.append((collection, query, n_results))
        return self.docs


class ScriptedLLM:
    async def invoke(self, messages):  # pragma: no cover - defensive
        raise AssertionError("LLM should not be invoked by retrieve/echo-only graphs")


def _retrieve_definition(**node_overrides) -> dict:
    node = {
        "name": "load_bok",
        "type": "retrieve",
        "collection_template": "{bok_id}-knowledge",
        "query_template": "info about {topic}",
        "n_results": 10,
        "output_key": "knowledge_docs",
    }
    node.update(node_overrides)
    return {
        "nodes": [node],
        "edges": [
            {"from": "START", "to": "load_bok"},
            {"from": "load_bok", "to": "END"},
        ],
        "state": {
            "type": "object",
            "properties": {
                "bok_id": {"type": "string"},
                "topic": {"type": "string"},
                "knowledge_docs": {"type": "string"},
            },
        },
    }


class TestRetrieveNode:
    async def test_us1_as3_single_query_single_fill(self):
        retriever = FakeRetriever(docs=["chunk one", "chunk two"])
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        final = await graph.invoke({"bok_id": "ls-101", "topic": "facilitation"})
        assert retriever.calls == [("ls-101-knowledge", "info about facilitation", 10)]
        assert final["knowledge_docs"] == "chunk one\n\nchunk two"

    async def test_us1_as3_hostile_brace_values_are_literal(self):
        """Member-derived state containing brace/format-directive text must
        appear literally in the filled query — never re-interpreted
        (FR-011, R-2)."""
        retriever = FakeRetriever()
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        hostile_topic = "{bok_id} and {0} and %s and {{nested}}"
        await graph.invoke({"bok_id": "real-id", "topic": hostile_topic})
        assert len(retriever.calls) == 1
        collection, query, n = retriever.calls[0]
        assert collection == "real-id-knowledge"
        assert query == f"info about {hostile_topic}"
        # The hostile text must not have been re-parsed: it still contains
        # its literal braces, not "real-id" substituted a second time.
        assert "{bok_id}" in query
        assert "{0}" in query

    async def test_us1_as3_hostile_resolvable_var_reference_is_not_reinterpreted(self):
        """A hostile value containing ONLY a resolvable variable reference
        (no positional token like `{0}`) must also pass through literally.

        The sibling test above uses `{0}` in its hostile fixture, which
        makes a naive fail-open two-pass re-interpretation ("format the
        already-filled query a second time") raise (positional args are
        never supplied) rather than silently leak. A `{bok_id}` reference
        has no such escape hatch: a second format pass would happily
        substitute the real `bok_id` value into what should be inert
        member-typed text, cross-field-leaking another field's value into
        the query (FR-011, R-2). This case fails under BOTH a fail-open and
        a fail-closed two-pass implementation, closing that gap."""
        retriever = FakeRetriever()
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        hostile_topic = "{bok_id} and {{nested}}"
        await graph.invoke({"bok_id": "secret-bok", "topic": hostile_topic})
        assert len(retriever.calls) == 1
        collection, query, n = retriever.calls[0]
        assert collection == "secret-bok-knowledge"
        assert query == f"info about {hostile_topic}"
        # The literal placeholder text survives untouched — critically, the
        # real `bok_id` value must NOT have been substituted into it a
        # second time.
        assert "{bok_id}" in query
        assert "secret-bok and" not in query

    async def test_empty_results_write_empty_string_and_continue(self):
        retriever = FakeRetriever(docs=[])
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        final = await graph.invoke({"bok_id": "x", "topic": "y"})
        assert final["knowledge_docs"] == ""

    async def test_unresolvable_template_variable_raises_named_error(self):
        definition = _retrieve_definition(query_template="info about {undeclared_var}")
        # `undeclared_var` is not in state schema at all — from_definition
        # doesn't validate template vars against state (state schema may add
        # fields later); the runtime raises when it can't resolve.
        definition["state"]["properties"]["undeclared_var"] = {"type": ["string", "null"]}
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM(), retriever=FakeRetriever())
        with pytest.raises(PromptGraphConfigError, match="undeclared_var"):
            await graph.invoke({"bok_id": "x", "topic": "y"})

    def test_n_results_out_of_range_rejected_at_parse_time(self):
        with pytest.raises(PromptGraphConfigError, match="n_results"):
            PromptGraph.from_definition(_retrieve_definition(n_results=0))
        with pytest.raises(PromptGraphConfigError, match="n_results"):
            PromptGraph.from_definition(_retrieve_definition(n_results=51))

    def test_retrieve_without_retriever_raises_at_compile_time(self):
        graph = PromptGraph.from_definition(_retrieve_definition())
        with pytest.raises(PromptGraphConfigError, match="knowledge store"):
            graph.compile(llm=ScriptedLLM(), retriever=None)

    def test_unknown_node_type_rejected_at_parse_time(self):
        definition = _retrieve_definition(type="bogus")
        with pytest.raises(PromptGraphConfigError, match="bogus"):
            PromptGraph.from_definition(definition)

    def test_collection_template_disallowed_variable_rejected_at_parse_time(self):
        """A payload cannot address an arbitrary collection: naming any
        variable other than the server-supplied `bok_id` in
        `collection_template` is a parse-time configuration error, not a
        runtime value the retriever ever sees."""
        definition = _retrieve_definition(
            collection_template="{victim_space_id}-knowledge"
        )
        with pytest.raises(PromptGraphConfigError, match="victim_space_id"):
            PromptGraph.from_definition(definition)

    def test_collection_template_mixing_bok_id_with_disallowed_variable_rejected(self):
        definition = _retrieve_definition(
            collection_template="{bok_id}-{topic}-knowledge"
        )
        with pytest.raises(PromptGraphConfigError, match="topic"):
            PromptGraph.from_definition(definition)

    def test_collection_template_bok_id_only_still_allowed(self):
        """Regression guard: the one legitimate shape still parses fine."""
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=FakeRetriever())

    async def test_retrieve_node_enforces_context_budget_on_oversized_docs(self):
        """Unlike every other retrieval path, the retrieve node previously
        joined documents with no context budget. Oversized results must be
        truncated to the repo's 20_000-char idiom, not pushed whole into the
        next LLM prompt."""
        big_doc = "x" * 15_000
        retriever = FakeRetriever(docs=[big_doc, big_doc, big_doc])
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        final = await graph.invoke({"bok_id": "ls-101", "topic": "facilitation"})
        assert len(final["knowledge_docs"]) <= 20_000
        # First doc alone (15_000 chars) fits; the second would push the
        # running total over budget with its doc + separator, so only one
        # of the three oversized docs survives.
        assert final["knowledge_docs"] == big_doc

    async def test_single_oversized_doc_still_returned_alone(self):
        """A single document that alone exceeds the budget still comes
        through rather than being silently dropped to empty — that would
        look indistinguishable from a failed/empty retrieval."""
        huge_doc = "x" * 25_000
        retriever = FakeRetriever(docs=[huge_doc])
        graph = PromptGraph.from_definition(_retrieve_definition())
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        final = await graph.invoke({"bok_id": "ls-101", "topic": "facilitation"})
        assert final["knowledge_docs"] == huge_doc

    async def test_input_variables_field_is_documentation_only(self):
        """An `input_variables` list on a retrieve node must not be
        load-bearing — variables are discovered from the templates."""
        retriever = FakeRetriever()
        definition = _retrieve_definition(input_variables=["not_a_real_var"])
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM(), retriever=retriever)
        final = await graph.invoke({"bok_id": "x", "topic": "y"})
        assert final["knowledge_docs"] != ""

    def test_retrieve_output_key_undeclared_in_state_rejected_at_compile_time(self):
        """A retrieve node's `output_key` not declared in the state schema
        would silently drop the retrieved result on LangGraph state merge —
        this must be a named `PromptGraphConfigError` at compile time, not a
        silent no-op discovered later."""
        definition = _retrieve_definition(output_key="undeclared_key")
        graph = PromptGraph.from_definition(definition)
        with pytest.raises(PromptGraphConfigError, match="load_bok.*undeclared_key"):
            graph.compile(llm=ScriptedLLM(), retriever=FakeRetriever())

    def test_echo_result_undeclared_in_state_rejected_at_compile_time(self):
        """An echo node's implicit `result` write must be declared in the
        state schema, or its output is silently dropped on state merge."""
        definition = {
            "nodes": [{"name": "ask", "type": "echo", "source": "question"}],
            "edges": [
                {"from": "START", "to": "ask"},
                {"from": "ask", "to": "END"},
            ],
            "state": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
            },
        }
        graph = PromptGraph.from_definition(definition)
        with pytest.raises(PromptGraphConfigError, match="ask.*result"):
            graph.compile(llm=ScriptedLLM())

    def test_retrieve_missing_collection_template_rejected_at_parse_time(self):
        definition = _retrieve_definition(collection_template="")
        with pytest.raises(PromptGraphConfigError, match="collection_template"):
            PromptGraph.from_definition(definition)

    def test_retrieve_missing_query_template_rejected_at_parse_time(self):
        definition = _retrieve_definition(query_template="")
        with pytest.raises(PromptGraphConfigError, match="query_template"):
            PromptGraph.from_definition(definition)

    def test_node_missing_name_rejected_at_parse_time(self):
        definition = _retrieve_definition()
        del definition["nodes"][0]["name"]
        with pytest.raises(PromptGraphConfigError, match="name"):
            PromptGraph.from_definition(definition)

    async def test_special_node_name_precedence_over_type(self):
        """Expert's existing name-keyed special-node injection is checked
        BEFORE type dispatch — a node named "retrieve" with no `type` field
        still uses the special node, not the declarative retrieve dispatch
        (dispatch order proof, FR-006)."""
        definition = {
            "nodes": [
                {"name": "retrieve", "input_variables": ["q"], "prompt": "unused: {q}"},
            ],
            "edges": [
                {"from": "START", "to": "retrieve"},
                {"from": "retrieve", "to": "END"},
            ],
            "state": {
                "type": "object",
                "properties": {"q": {"type": "string"}, "result": {"type": "string"}},
            },
        }
        graph = PromptGraph.from_definition(definition)

        async def special(state: dict) -> dict:
            return {"result": "special-node-ran"}

        graph.compile(llm=ScriptedLLM(), special_nodes={"retrieve": special})
        final = await graph.invoke({"q": "hi"})
        assert final["result"] == "special-node-ran"


def _echo_definition(source: str = "question") -> dict:
    return {
        "nodes": [
            {"name": "ask", "type": "echo", "source": source},
        ],
        "edges": [
            {"from": "START", "to": "ask"},
            {"from": "ask", "to": "END"},
        ],
        "state": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "flag": {"type": "boolean"},
                "count": {"type": "integer"},
                "empty_str": {"type": "string"},
                "result": {"type": "string"},
            },
        },
    }


class TestEchoNode:
    async def test_us1_as4_echoes_verbatim_zero_llm_calls(self):
        llm = ScriptedLLM()
        graph = PromptGraph.from_definition(_echo_definition())
        graph.compile(llm=llm)
        final = await graph.invoke({"question": "What is Alkemio?"})
        assert final["result"] == "What is Alkemio?"

    async def test_absent_or_none_source_echoes_empty_string(self):
        definition = _echo_definition(source="undeclared")
        definition["state"]["properties"]["undeclared"] = {"type": ["string", "null"]}
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({"question": "x"})
        assert final["result"] == ""

    async def test_falsy_values_echo_exact_string_form_no_collapse(self):
        graph = PromptGraph.from_definition(_echo_definition(source="count"))
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({"count": 0})
        assert final["result"] == "0"

        graph2 = PromptGraph.from_definition(_echo_definition(source="flag"))
        graph2.compile(llm=ScriptedLLM())
        final2 = await graph2.invoke({"flag": False})
        assert final2["result"] == "False"

        graph3 = PromptGraph.from_definition(_echo_definition(source="empty_str"))
        graph3.compile(llm=ScriptedLLM())
        final3 = await graph3.invoke({"empty_str": ""})
        assert final3["result"] == ""

    def test_echo_missing_source_rejected_at_parse_time(self):
        with pytest.raises(PromptGraphConfigError, match="source"):
            PromptGraph.from_definition(_echo_definition(source=""))
