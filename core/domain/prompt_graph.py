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
    def _recover_fields(raw_text: str, model: type[BaseModel]) -> dict | None:
        """Best-effort recovery of model fields from free-form LLM output.

        Used when ``PydanticOutputParser`` fails because the LLM wrapped
        the required keys under extra objects.  We find the JSON body,
        walk it and pluck any key matching a model field.  Missing
        required fields abort the recovery.
        """
        import json as _json
        import re as _re

        # Find the first {...} block, allowing nested braces.
        match = _re.search(r"\{.*\}", raw_text, _re.DOTALL)
        if not match:
            return None
        try:
            payload = _json.loads(match.group(0))
        except Exception:
            return None

        field_names = set(model.model_fields.keys())
        # Also accept ``<field>_text`` keys — small LLMs sometimes rename
        # the canonical field and stash the real content alongside.
        alt_aliases = {f"{n}_text": n for n in field_names}

        found: dict = {}

        def _maybe_set(key: str, value) -> None:
            # Prefer non-null over null: if we already have a null value
            # for this key, allow a later non-null entry to replace it.
            if key not in found or (found[key] is None and value is not None):
                found[key] = value

        def _walk(obj) -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in field_names:
                        _maybe_set(k, v)
                    elif k in alt_aliases:
                        _maybe_set(alt_aliases[k], v)
                    _walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(payload)
        if not found:
            return None
        # Drop null values for required fields so the validator can use
        # defaults or report the real missing-field error.
        for name, finfo in model.model_fields.items():
            if finfo.is_required() and found.get(name) is None:
                found.pop(name, None)

        required = {
            name for name, finfo in model.model_fields.items()
            if finfo.is_required()
        }
        if required - found.keys():
            return None
        try:
            return model.model_validate(found).model_dump()
        except Exception:
            return None

    @staticmethod
    def _make_nullable(prop_def: dict) -> dict:
        """Broaden a property schema to also accept ``null``."""
        if not isinstance(prop_def, dict):
            return prop_def
        result = dict(prop_def)
        t = result.get("type")
        if isinstance(t, str) and t != "null":
            result["type"] = [t, "null"]
        elif isinstance(t, list) and "null" not in t:
            result["type"] = list(t) + ["null"]
        result.setdefault("default", None)
        return result

    @staticmethod
    def _normalize_schema(schema: dict | None) -> dict | None:
        """Convert the server's list-based data-struct to JSON Schema form."""
        if not isinstance(schema, dict):
            return schema

        schema = dict(schema)  # shallow copy so we don't mutate the input

        props = schema.get("properties")
        if isinstance(props, list):
            normalised: dict[str, dict] = {}
            required: list[str] = []
            for entry in props:
                if not isinstance(entry, dict) or "name" not in entry:
                    continue
                name = entry["name"]
                prop_def = {
                    k: v for k, v in entry.items()
                    if k not in ("name", "optional")
                }
                prop_def = PromptGraph._normalize_schema(prop_def) or prop_def
                if entry.get("optional", False):
                    prop_def = PromptGraph._make_nullable(prop_def)
                else:
                    required.append(name)
                normalised[name] = prop_def
            schema["properties"] = normalised
            if required and "required" not in schema:
                schema["required"] = required
            if schema.get("type") is None:
                schema["type"] = "object"
        elif isinstance(props, dict):
            schema["properties"] = {
                k: PromptGraph._normalize_schema(v) or v
                for k, v in props.items()
            }

        if isinstance(schema.get("items"), dict):
            schema["items"] = PromptGraph._normalize_schema(schema["items"])

        if isinstance(schema.get("additionalProperties"), dict):
            schema["additionalProperties"] = PromptGraph._normalize_schema(
                schema["additionalProperties"]
            )

        for combinator in ("anyOf", "oneOf", "allOf"):
            if isinstance(schema.get(combinator), list):
                schema[combinator] = [
                    PromptGraph._normalize_schema(s) or s
                    for s in schema[combinator]
                ]

        return schema

    @staticmethod
    def _build_state_model(schema: dict) -> type[BaseModel]:
        """Build a dynamic Pydantic model from a JSON schema."""
        schema = PromptGraph._normalize_schema(schema) or {}
        # Transform list-type properties to have default empty list
        properties = schema.get("properties", {})
        for _prop_name, prop_def in properties.items():
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
        schema = PromptGraph._normalize_schema(node.output_schema)
        if not schema:
            return None
        return create_model(schema)

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
                graph.add_node(
                    node_name,
                    self._wrap_special_node(special_nodes[node_name]),
                )
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

        # `llm` may be our LLMPort adapter (e.g. LangChainLLMAdapter);
        # the LangChain Expression Language pipe needs the underlying
        # BaseChatModel.  Prefer the `_llm` attribute, fall back to the
        # adapter itself so callers passing a raw Runnable still work.
        runnable_llm = getattr(llm, "_llm", None) or llm

        async def node_fn(state) -> dict:
            # State may be either a dict (Pydantic TypedDict mode) or a
            # Pydantic model instance (schema-based StateGraph).
            def _read(key: str, default=""):
                if isinstance(state, dict):
                    return state.get(key, default)
                return getattr(state, key, default)

            # Extract input variables from state
            inputs = {}
            for var in node.input_variables:
                value = _read(var, "")
                if isinstance(value, list):
                    value = "\n".join(str(v) for v in value)
                inputs[var] = value if value is not None else ""

            if output_model:
                parser = PydanticOutputParser(pydantic_object=output_model)
                inputs["format_instructions"] = parser.get_format_instructions()
                raw_chain = prompt_template | runnable_llm
                raw = await raw_chain.ainvoke(inputs)
                raw_text = raw.content if hasattr(raw, "content") else str(raw)
                try:
                    result = parser.parse(raw_text)
                    return result.model_dump()
                except Exception as exc:
                    logger.warning(
                        "Structured parse failed for node %s: %s — "
                        "attempting recovery",
                        node.name, exc,
                    )
                    recovered = PromptGraph._recover_fields(
                        raw_text, output_model
                    )
                    if recovered is not None:
                        return recovered
                    raise
            else:
                chain = prompt_template | runnable_llm
                result = await chain.ainvoke(inputs)
                content = result.content if hasattr(result, "content") else str(result)
                return {"result": content}

        return node_fn

    @staticmethod
    def _state_to_dict(state) -> dict:
        """Convert a LangGraph state to a plain dict."""
        if isinstance(state, dict):
            return state
        if hasattr(state, "model_dump"):
            return state.model_dump()
        try:
            return dict(state)
        except Exception:
            return state

    @staticmethod
    def _wrap_special_node(fn: Callable) -> Callable:
        """Wrap a user-supplied node so it always sees a dict state."""
        async def wrapped(state):
            return await fn(PromptGraph._state_to_dict(state))
        return wrapped

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

        result = await self._compiled.ainvoke(initial_state)
        return self._state_to_dict(result)

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
