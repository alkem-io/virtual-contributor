"""Unit tests for PromptGraph."""

from __future__ import annotations

import pytest

from core.domain.prompt_graph import Edge, Node, PromptGraph


class TestPromptGraphStructure:
    def test_from_definition(self):
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

    def test_node_dataclass(self):
        node = Node(name="test", input_variables=["x"], prompt="Process {x}")
        assert node.name == "test"
        assert node.input_variables == ["x"]
        assert node.output_model is None

    def test_edge_dataclass(self):
        edge = Edge(from_node="START", to_node="analyze")
        assert edge.from_node == "START"
        assert edge.to_node == "analyze"

    def test_empty_graph(self):
        graph = PromptGraph(nodes={}, edges=[])
        assert graph.nodes == {}
        assert graph.edges == []

    def test_invoke_without_compile_raises(self):
        graph = PromptGraph(nodes={}, edges=[])
        with pytest.raises(RuntimeError, match="not compiled"):
            import asyncio
            asyncio.get_event_loop().run_until_complete(graph.invoke({}))

    def test_state_model_building(self):
        schema = {
            "type": "object",
            "properties": {
                "question": {"type": "string", "default": ""},
                "answer": {"type": "string", "default": ""},
                "items": {"type": "array", "items": {"type": "string"}},
            },
        }
        graph = PromptGraph(nodes={}, edges=[], state_schema=schema)
        assert graph._state_model is not None
