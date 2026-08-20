"""Unit tests — declarative conditional edges (FR-001, US1)."""

from __future__ import annotations

import pytest

from core.domain.prompt_graph import PromptGraph, PromptGraphConfigError


#: Distinct seeded values for the two branch nodes below, so a test's
#: assertion on `final["result"]` names WHICH node ran rather than merely
#: confirming a value round-tripped. Both nodes echo the same `value` field
#: prior to this fix, which made every assertion pass even with the routing
#: map inverted or the conditional edge deleted outright.
_NEXT_RAN = "next-branch-ran"
_ASK_RAN = "ask-branch-ran"


def _base_definition(edges: list[dict], extra_state: dict | None = None) -> dict:
    state_props = {
        "complete": {"type": "boolean"},
        "value": {"type": "string"},
        "next_marker": {"type": "string"},
        "ask_marker": {"type": "string"},
        "result": {"type": "string"},
    }
    if extra_state:
        state_props.update(extra_state)
    return {
        "nodes": [
            {
                "name": "check",
                "type": "echo",
                "source": "value",
            },
            {
                # Echoes its OWN marker field — distinct from "ask" below —
                # so a test can tell from `final["result"]` alone that THIS
                # node, and not the other branch, actually ran.
                "name": "next",
                "type": "echo",
                "source": "next_marker",
            },
            {
                "name": "ask",
                "type": "echo",
                "source": "ask_marker",
            },
        ],
        "edges": edges,
        "state": {"type": "object", "properties": state_props},
    }


def _branch_markers() -> dict:
    """Initial-state fragment seeding both branch markers with distinct,
    recognisable values — merge into every `invoke()` call that routes
    through `next` or `ask` so the assertion discriminates the two."""
    return {"next_marker": _NEXT_RAN, "ask_marker": _ASK_RAN}


class ScriptedLLM:
    """Never invoked in these tests — conditional-edge tests use echo nodes."""

    async def invoke(self, messages):  # pragma: no cover - defensive
        raise AssertionError("LLM should not be invoked by echo-only graphs")


class TestConditionalEdgeRouting:
    async def test_us1_as1_false_routes_to_ask_not_next(self):
        """check outputs complete=false -> ask ran, next did not."""
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        # check is an echo node writing {"result": value}, so it does not
        # itself write `complete` — seed `complete` directly in initial state
        # and route on it (the router reads whatever state carries, however
        # it got there — a structured LLM node's merged output in real use).
        # `next` and `ask` each echo their OWN distinct marker field, so the
        # final result names which one actually ran.
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({
            "complete": False, "value": "the question", **_branch_markers(),
        })
        assert final["result"] == _ASK_RAN

    async def test_us1_as2_true_routes_to_next_not_ask(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({
            "complete": True, "value": "next-value", **_branch_markers(),
        })
        assert final["result"] == _NEXT_RAN

    async def test_boolean_true_matches_lowercase_string_key(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({"complete": True, "value": "x", **_branch_markers()})
        assert final["result"] == _NEXT_RAN

    async def test_none_value_routes_to_default_when_declared(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {
                "from": "check", "on": "missing_field",
                "map": {"true": "next"}, "default": "ask",
            },
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ], extra_state={"missing_field": {"type": ["boolean", "null"]}})
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({"value": "unrouted-default", **_branch_markers()})
        assert final["result"] == _ASK_RAN

    async def test_literal_none_map_key_never_matched_by_absent_value(self):
        """An absent field must never stringify to `"none"` and match a
        literal `"none"` map key — it takes the no-match path directly."""
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {
                "from": "check", "on": "missing_field",
                "map": {"none": "next"}, "default": "ask",
            },
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ], extra_state={"missing_field": {"type": ["boolean", "null"]}})
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({"value": "default-not-none", **_branch_markers()})
        # Routed via default (ask), not via the "none" map key (next) — each
        # branch echoes its own marker field, so the two are distinguishable.
        assert final["result"] == _ASK_RAN

    async def test_us1_as6_unmatched_value_no_default_raises_config_error(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ], extra_state={"complete": {"type": "string"}})
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        with pytest.raises(PromptGraphConfigError, match="check.*complete"):
            await graph.invoke({"complete": "maybe", "value": "x"})

    async def test_end_target_valid_in_map(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "END", "false": "ask"}},
            {"from": "ask", "to": "END"},
        ])
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        final = await graph.invoke({"complete": True, "value": "unused"})
        # check is an echo node; its own write lands, no downstream ran.
        assert final["result"] == "unused"

    async def test_plain_edge_from_conditional_source_is_skipped(self):
        """A plain edge whose `from` is also a conditional source is ignored
        (conditional wins — prior-art semantics, FR-001)."""
        definition = _base_definition([
            {"from": "START", "to": "check"},
            # This plain edge should be IGNORED because "check" is also a
            # conditional source below.
            {"from": "check", "to": "next"},
            {"from": "check", "on": "complete", "map": {"true": "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        # complete=false must route to ask, proving the plain edge to `next`
        # was NOT registered (LangGraph would otherwise run both branches or
        # raise on ambiguous edges) — `ask`'s own marker in the result proves
        # it, not `next`'s.
        final = await graph.invoke({
            "complete": False, "value": "routed-via-conditional", **_branch_markers(),
        })
        assert final["result"] == _ASK_RAN

    def test_unknown_target_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "ghost", "false": "ask"}},
            {"from": "ask", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="ghost"):
            PromptGraph.from_definition(definition)

    def test_unknown_from_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "ghost_node", "on": "complete", "map": {"true": "next"}},
            {"from": "check", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="ghost_node"):
            PromptGraph.from_definition(definition)

    def test_unknown_default_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "next"}, "default": "ghost"},
            {"from": "next", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="ghost"):
            PromptGraph.from_definition(definition)

    def test_unknown_plain_edge_endpoint_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "ghost"},
        ])
        with pytest.raises(PromptGraphConfigError, match="ghost"):
            PromptGraph.from_definition(definition)

    def test_conditional_edge_missing_on_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "map": {"true": "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="'on'"):
            PromptGraph.from_definition(definition)

    def test_conditional_edge_non_string_map_key_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {True: "next", "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="map"):
            PromptGraph.from_definition(definition)

    def test_conditional_edge_non_string_map_target_rejected_at_parse_time(self):
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": ["next"], "false": "ask"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="map"):
            PromptGraph.from_definition(definition)

    def test_duplicate_conditional_edge_source_rejected_at_parse_time(self):
        """Two conditional edges from the same source node must be rejected
        here, at parse time, naming the construct — never left to hit
        LangGraph's raw ValueError on the second `add_conditional_edges`
        call for the same source."""
        definition = _base_definition([
            {"from": "START", "to": "check"},
            {"from": "check", "on": "complete", "map": {"true": "next", "false": "ask"}},
            {"from": "check", "on": "value", "map": {"x": "next"}},
            {"from": "next", "to": "END"},
            {"from": "ask", "to": "END"},
        ])
        with pytest.raises(PromptGraphConfigError, match="check"):
            PromptGraph.from_definition(definition)

    async def test_cyclic_conditional_graph_raises_not_infinite_loop(self):
        """A mis-authored cyclic payload is bounded by LangGraph's recursion
        limit and surfaces as a raised exception — never an unbounded loop
        (spec edge case 'graphs with cycles')."""
        definition = {
            "nodes": [
                {"name": "loop", "type": "echo", "source": "value"},
                {"name": "other", "type": "echo", "source": "value"},
            ],
            "edges": [
                {"from": "START", "to": "loop"},
                # Always routes back to itself — no default, but "true"
                # always matches since complete is always True below.
                {"from": "loop", "on": "complete", "map": {"true": "loop"}},
            ],
            "state": {
                "type": "object",
                "properties": {
                    "complete": {"type": "boolean"},
                    "value": {"type": "string"},
                    "result": {"type": "string"},
                },
            },
        }
        graph = PromptGraph.from_definition(definition)
        graph.compile(llm=ScriptedLLM())
        with pytest.raises(Exception):
            await graph.invoke({"complete": True, "value": "x"})

    def test_from_definition_back_compat_no_new_fields(self):
        """A definition using none of the new constructs parses to the
        same Node/Edge shapes as develop (SC-002 parse-side invariant)."""
        definition = {
            "nodes": [
                {"name": "analyze", "input_variables": ["question"], "prompt": "Analyze: {question}", "output": {}},
                {"name": "answer", "input_variables": ["analysis"], "prompt": "Answer: {analysis}", "output": {}},
            ],
            "edges": [
                {"from": "START", "to": "analyze"},
                {"from": "analyze", "to": "answer"},
                {"from": "answer", "to": "END"},
            ],
            "state": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "analysis": {"type": "string"},
                },
            },
        }
        graph = PromptGraph.from_definition(definition)
        assert "analyze" in graph.nodes
        assert "answer" in graph.nodes
        assert len(graph.edges) == 3
        assert graph.conditional_edges == []
        assert graph.nodes["analyze"].type == "llm"
