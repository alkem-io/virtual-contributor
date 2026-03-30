from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from json_schema_to_pydantic import create_model
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END, START
from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class Node:
    """A single node in the prompt graph."""
    name: str
    input_variables: list[str]
    prompt: str
    output_schema: dict = field(default_factory=dict)
    output_model: type[BaseModel] | None = None


@dataclass
class Edge:
    """A directed edge between two nodes."""
    from_node: str
    to_node: str


class PromptGraph:
    """Graph-based LLM workflow execution engine.

    Compiles a JSON graph definition into a LangGraph StateGraph
    for step-by-step LLM execution with structured output.
    """

    def __init__(
        self,
        nodes: dict[str, Node],
        edges: list[Edge],
        state_schema: dict | None = None,
        start_node: str = "START",
        end_node: str = "END",
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.start_node = start_node
        self.end_node = end_node
        self._state_model = self._build_state_model(state_schema) if state_schema else None
        self._compiled = None

    @staticmethod
    def _build_state_model(schema: dict) -> type[BaseModel]:
        """Build a dynamic Pydantic model from a JSON schema."""
        # Transform list-type properties to have default empty list
        properties = schema.get("properties", {})
        for prop_name, prop_def in properties.items():
            if prop_def.get("type") == "array":
                prop_def.setdefault("default", [])
            elif "default" not in prop_def:
                prop_def["default"] = None

        return create_model(schema)

    @staticmethod
    def _build_output_model(node: Node) -> type[BaseModel] | None:
        """Build a Pydantic output model from a node's output schema."""
        if not node.output_schema:
            return None
        return create_model(node.output_schema)

    def compile(
        self,
        llm: Any,
        special_nodes: dict[str, Callable] | None = None,
    ) -> PromptGraph:
        """Compile the graph into a runnable LangGraph StateGraph."""
        special_nodes = special_nodes or {}

        if self._state_model is None:
            raise ValueError("Cannot compile graph without a state schema")

        graph = StateGraph(self._state_model)

        for node_name, node in self.nodes.items():
            if node_name in special_nodes:
                # Inject special node as a raw callable
                graph.add_node(node_name, special_nodes[node_name])
            else:
                # Build LLM chain node
                output_model = self._build_output_model(node)
                node.output_model = output_model
                chain_fn = self._make_chain_node(node, llm, output_model)
                graph.add_node(node_name, chain_fn)

        # Add edges
        for edge in self.edges:
            from_node = START if edge.from_node == "START" else edge.from_node
            to_node = END if edge.to_node == "END" else edge.to_node
            graph.add_edge(from_node, to_node)

        self._compiled = graph.compile()
        return self

    @staticmethod
    def _make_chain_node(
        node: Node, llm: Any, output_model: type[BaseModel] | None
    ) -> Callable:
        """Create a LangGraph node function from a prompt template + LLM."""
        prompt_template = ChatPromptTemplate.from_template(node.prompt)

        async def node_fn(state: dict) -> dict:
            # Extract input variables from state
            inputs = {}
            for var in node.input_variables:
                value = state.get(var, "")
                if isinstance(value, list):
                    value = "\n".join(str(v) for v in value)
                inputs[var] = value if value is not None else ""

            if output_model:
                parser = PydanticOutputParser(pydantic_object=output_model)
                inputs["format_instructions"] = parser.get_format_instructions()
                chain = prompt_template | llm | parser
                result = await chain.ainvoke(inputs)
                return result.model_dump()
            else:
                chain = prompt_template | llm
                result = await chain.ainvoke(inputs)
                content = result.content if hasattr(result, "content") else str(result)
                return {"result": content}

        return node_fn

    async def stream(
        self, initial_state: dict, stream_mode: str = "updates"
    ) -> AsyncIterator[dict]:
        """Stream graph execution updates."""
        if self._compiled is None:
            raise RuntimeError("Graph not compiled — call compile() first")

        async for event in self._compiled.astream(initial_state, stream_mode=stream_mode):
            yield event

    async def invoke(self, initial_state: dict) -> dict:
        """Run the full graph and return final state."""
        if self._compiled is None:
            raise RuntimeError("Graph not compiled — call compile() first")

        return await self._compiled.ainvoke(initial_state)

    @classmethod
    def from_definition(cls, definition: dict) -> PromptGraph:
        """Build a PromptGraph from a JSON definition.

        Expected format:
        {
            "nodes": [{"name": "...", "input_variables": [...], "prompt": "...", "output": {...}}],
            "edges": [{"from": "...", "to": "..."}],
            "state": {JSON schema},
            "start": "START",
            "end": "END"
        }
        """
        nodes = {}
        for node_def in definition.get("nodes", []):
            node = Node(
                name=node_def["name"],
                input_variables=node_def.get("input_variables", []),
                prompt=node_def.get("prompt", ""),
                output_schema=node_def.get("output", {}),
            )
            nodes[node.name] = node

        edges = []
        for edge_def in definition.get("edges", []):
            edges.append(Edge(
                from_node=edge_def.get("from", "START"),
                to_node=edge_def.get("to", "END"),
            ))

        return cls(
            nodes=nodes,
            edges=edges,
            state_schema=definition.get("state"),
            start_node=definition.get("start", "START"),
            end_node=definition.get("end", "END"),
        )
