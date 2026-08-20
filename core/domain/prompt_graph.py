from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field
from typing import Any, Awaitable, AsyncIterator, Callable

from json_schema_to_pydantic import create_model
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END, START
from pydantic import BaseModel

from core.domain.prompts_shared import INTER_BLOCK_SEPARATOR

logger = logging.getLogger(__name__)

#: Value form bound in raised errors and log lines. A routing value can
#: originate in member-typed chat text (a structured field a node extracted
#: from the conversation); a runaway value must never blow up an error
#: message or land verbatim, unbounded, in a log line (FR-009 — construct
#: names and error types only, never member content).
_MAX_LOGGED_VALUE_CHARS = 64

#: The only template variable a `collection_template` may reference. It is
#: sourced exclusively from the engine-seeded `bok_id` state key — itself
#: taken from `Input.bodyOfKnowledgeID`, never from a member/LLM-derived
#: field — the same tenancy binding the expert engine enforces server-side
#: (plugins/expert/plugin.py). A payload naming any other variable there
#: could otherwise address an arbitrary knowledge-store collection outside
#: the caller's own body of knowledge; this is a parse-time configuration
#: error, not a runtime authorization check, so a hostile payload is
#: rejected before any store query is ever made.
_ALLOWED_COLLECTION_TEMPLATE_VARS = frozenset({"bok_id"})

#: Default context budget applied to documents joined by a declarative
#: `retrieve` node, mirroring the `max_context_chars` idiom every other
#: retrieval path in this repo enforces (`core/config.py`,
#: `core/domain/routing.py`, `plugins/expert/plugin.py`,
#: `plugins/guidance/plugin.py`). A payload may override this per node via
#: the optional `max_context_chars` field (bounded by the min/max below) —
#: the fixed 20,000-char default silently dropped trailing documents on a
#: full `n_results=10` result set at the deployed ingest chunk size (9,000
#: characters — `CHUNK_SIZE` in the infra-ops configMap, also
#: `core/domain/routing.py` and `docs/adr/0016`), so a node whose own
#: retrieval volume needs a larger budget can say so explicitly rather than
#: lose documents FR-002 says are "used as returned".
_RETRIEVE_MAX_CONTEXT_CHARS_DEFAULT = 20_000

#: Bounds for a payload's per-node `max_context_chars` override. The floor
#: keeps the budget a real budget (not effectively unlimited for small
#: values); the ceiling keeps it a security control — the field lets a
#: payload widen the context sent to the next LLM call, so it stays capped
#: rather than becoming an unbounded escape hatch from the budget entirely.
#: Raised to 120,000 so a full `n_results=10` result set at the deployed
#: 9,000-char ingest chunk size (10 * 9000 + separators ~= 90,018 chars)
#: fits within the ceiling with margin, rather than being unfixable by any
#: in-range payload override.
_RETRIEVE_MAX_CONTEXT_CHARS_MIN = 1_000
_RETRIEVE_MAX_CONTEXT_CHARS_MAX = 120_000

#: Parse-time caps on total graph size. A declarative payload with no
#: node/edge ceiling could fan out to hundreds of nodes, each one an LLM or
#: retrieve invocation — a single superstep can run many nodes, so an
#: unbounded node count is effectively an unbounded burst of provider calls
#: and knowledge-store queries per inbound message. Sized well above the
#: shipped workshop-design payload (a handful of nodes) and any plausible
#: hand-authored graph, while still refusing a runaway fan-out payload at
#: parse time rather than mid-execution.
_MAX_GRAPH_NODES = 50
_MAX_GRAPH_EDGES = 100

#: Recursion ceiling passed to every graph run. A declarative conditional
#: edge whose ``map``/``default`` routes back to an already-visited node
#: forms a cycle that neither ``from_definition`` nor ``compile()`` detects
#: (detecting it statically would require analyzing runtime-only routing
#: values). Left at LangGraph's own default of 10007, a cyclic payload with
#: an LLM node inside the cycle would run until the pipeline's own multi-hour
#: timeout, burning provider budget the whole time and — since the RabbitMQ
#: consumer processes one message at a time — blocking every other message
#: behind it. A small ceiling instead fails a mis-authored cyclic graph in
#: well under a second.
_GRAPH_RECURSION_LIMIT = 50


class PromptGraphConfigError(ValueError):
    """A prompt-graph JSON definition is malformed or unsatisfiable.

    Raised at parse time (unknown node type, out-of-range ``n_results``,
    an edge or node type naming an undeclared node) or at compile/run time
    (a conditional edge with no matching branch and no default; a retrieve
    node with no retriever configured; a retrieve template variable with no
    state value). Always names the offending node/field so the caller's
    standard error response is diagnosable without exposing member content.
    """


def _bounded_value_repr(value: Any) -> str:
    """A safe, length-capped string form of a routing value for error text.

    Routing values can be model output derived from a member's own chat
    (e.g. a structured field extracted from the conversation) — see FR-009.
    This never appears in a log line; it only appears in a raised exception
    message that the caller's error handler reduces to an error type before
    logging.
    """
    text = str(value)
    if len(text) > _MAX_LOGGED_VALUE_CHARS:
        return text[:_MAX_LOGGED_VALUE_CHARS] + "…"
    return text


@dataclass
class Node:
    """A single node in the prompt graph.

    ``type`` discriminates the node kind: ``"llm"`` (default, existing
    behaviour — prompt template + optional structured output), ``"retrieve"``
    (declarative knowledge-store query), or ``"echo"`` (verbatim state-field
    passthrough, no LLM call). The retrieve/echo-only fields are ignored for
    ``"llm"`` nodes and vice versa.
    """
    name: str
    input_variables: list[str]
    prompt: str
    output_schema: dict = field(default_factory=dict)
    output_model: type[BaseModel] | None = None
    type: str = "llm"
    collection_template: str = ""
    query_template: str = ""
    n_results: int = 10
    output_key: str = "knowledge_docs"
    source: str = ""
    max_context_chars: int = _RETRIEVE_MAX_CONTEXT_CHARS_DEFAULT


@dataclass
class Edge:
    """A directed edge between two nodes."""
    from_node: str
    to_node: str


@dataclass
class ConditionalEdge:
    """A declarative conditional edge (FR-001).

    At runtime, ``on_field`` is read from state and matched — as a
    case-insensitive string — against ``path_map``'s (already lower-cased)
    keys. A miss routes to ``default`` when declared, else raises
    :class:`PromptGraphConfigError`.
    """
    from_node: str
    on_field: str
    path_map: dict[str, str]
    default: str | None = None


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
        conditional_edges: list[ConditionalEdge] | None = None,
    ) -> None:
        self.nodes = nodes
        self.edges = edges
        self.start_node = start_node
        self.end_node = end_node
        self.conditional_edges = conditional_edges or []
        self._state_model = self._build_state_model(state_schema) if state_schema else None
        self._compiled = None

    @staticmethod
    def _default_for_annotation(annotation: Any) -> Any:
        """Pick a permissive default value for a Pydantic field annotation.

        Used by :meth:`_recover_fields` to fill in fields that the LLM
        dropped entirely. The intent is to keep the response flowing when
        a small model omits an auxiliary required field (e.g.
        ``answer_language``) rather than dead-lettering the whole message.
        """
        import typing

        origin = typing.get_origin(annotation)

        # Unwrap Optional[X] / Union[X, None] → X (first non-None arg).
        if origin is typing.Union or origin is getattr(
            __import__("types"), "UnionType", None
        ):
            args = [a for a in typing.get_args(annotation) if a is not type(None)]
            if not args:
                return None
            annotation = args[0]
            origin = typing.get_origin(annotation)

        if annotation is str:
            return ""
        if annotation is bool:
            return False
        if annotation in (int, float):
            return 0
        if origin is list or annotation is list:
            return []
        if origin is dict or annotation is dict:
            return {}
        # Nested BaseModel or unknown → try {}; Pydantic will coerce or fail.
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return {}
        return None

    @staticmethod
    def _recover_fields(raw_text: str, model: type[BaseModel]) -> dict | None:
        """Best-effort recovery of model fields from free-form LLM output.

        Used when ``PydanticOutputParser`` fails because the LLM wrapped
        the required keys under extra objects, or dropped a required
        auxiliary field (common with small/terse models). We find the JSON
        body, walk it, pluck any key matching a model field, and fill
        missing required fields with type-appropriate defaults so the
        response can still flow.
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
        # defaults or we can fill them below.
        for name, finfo in model.model_fields.items():
            if finfo.is_required() and found.get(name) is None:
                found.pop(name, None)

        required = {
            name for name, finfo in model.model_fields.items()
            if finfo.is_required()
        }
        missing_required = required - found.keys()
        if missing_required:
            # Fill missing required fields with type-appropriate defaults.
            # This keeps responses flowing when a small LLM drops an
            # auxiliary field (e.g. ``answer_language``) rather than
            # failing the whole message.
            filled = []
            for name in missing_required:
                finfo = model.model_fields[name]
                found[name] = PromptGraph._default_for_annotation(
                    finfo.annotation
                )
                filled.append(name)
            logger.warning(
                "Recovery filled missing required fields with defaults: %s",
                ", ".join(sorted(filled)),
            )
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
        retriever: Callable[[str, str, int], Awaitable[list[str]]] | None = None,
    ) -> PromptGraph:
        """Compile the graph into a runnable LangGraph StateGraph.

        ``retriever`` is an optional host-supplied async callable
        ``(collection, query, n_results) -> list[str]`` that ``"retrieve"``
        typed nodes are compiled onto (FR-002). The graph domain object never
        imports a knowledge-store port — the plugin owns that and passes the
        callback in, the same injection seam already used for expert's
        name-keyed special nodes.
        """
        special_nodes = special_nodes or {}

        if self._state_model is None:
            raise ValueError("Cannot compile graph without a state schema")

        graph = StateGraph(self._state_model)

        conditional_sources = {edge.from_node for edge in self.conditional_edges}

        for node_name, node in self.nodes.items():
            if node_name in special_nodes:
                # Inject special node as a raw callable — expert's existing
                # name-keyed seam. Checked FIRST so a declarative `type` field
                # can never hijack it (FR-006): the two mechanisms key on
                # different fields (name vs type) and this order keeps that
                # true even for a node named e.g. "retrieve" with no `type`.
                graph.add_node(
                    node_name,
                    self._wrap_special_node(special_nodes[node_name]),
                )
            elif node.type == "retrieve":
                if retriever is None:
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}' requires a knowledge "
                        "store, but none is configured for this engine "
                        "instance"
                    )
                if node.output_key not in self._state_model.model_fields:
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}': output_key "
                        f"'{node.output_key}' is not declared in the state "
                        "schema, so its result would be silently dropped "
                        "on state merge"
                    )
                graph.add_node(node_name, self._make_retrieve_node(node, retriever))
            elif node.type == "echo":
                if "result" not in self._state_model.model_fields:
                    raise PromptGraphConfigError(
                        f"echo node '{node_name}': state schema does not "
                        "declare a 'result' field, so its output would be "
                        "silently dropped on state merge"
                    )
                graph.add_node(node_name, self._make_echo_node(node))
            elif node.type == "llm":
                # Build LLM chain node (existing, default behaviour).
                output_model = self._build_output_model(node)
                node.output_model = output_model
                chain_fn = self._make_chain_node(node, llm, output_model)
                graph.add_node(node_name, chain_fn)
            else:
                raise PromptGraphConfigError(
                    f"node '{node_name}' declares unknown type '{node.type}'"
                )

        # Plain edges — skip any whose source is also a conditional source
        # (conditional wins; matches the 031-branch prior-art semantics).
        for edge in self.edges:
            if edge.from_node in conditional_sources:
                continue
            from_node = START if edge.from_node == "START" else edge.from_node
            to_node = END if edge.to_node == "END" else edge.to_node
            graph.add_edge(from_node, to_node)

        # Conditional edges (FR-001). LangGraph's `add_conditional_edges`
        # calls `router(state)` and looks up its return value in `ends` to
        # find the real destination — so `router` returns the RAW target
        # name (from `path_map`/`default`, pre-"END"-translation) and `ends`
        # maps every possible raw target name to its translated destination.
        for cond in self.conditional_edges:
            router = self._make_router(cond)
            targets = set(cond.path_map.values())
            if cond.default is not None:
                targets.add(cond.default)
            ends = {t: (END if t == "END" else t) for t in targets}
            source = START if cond.from_node == "START" else cond.from_node
            graph.add_conditional_edges(source, router, ends)

        self._compiled = graph.compile()
        return self

    @staticmethod
    def _read(state, key: str, default: Any = None) -> Any:
        """Read a field from state, whether it is a dict or a Pydantic model."""
        if isinstance(state, dict):
            return state.get(key, default)
        return getattr(state, key, default)

    @classmethod
    def _make_router(cls, cond: ConditionalEdge) -> Callable[[Any], str]:
        """Build the router closure LangGraph calls for one conditional edge."""

        def router(state) -> str:
            value = cls._read(state, cond.on_field, None)
            # `None`/absent takes the no-match path directly — never
            # stringified — so a literal `"none"` map key can never match an
            # absent/undeclared field (spec edge case).
            key = None if value is None else str(value).lower()
            if key is not None and key in cond.path_map:
                return cond.path_map[key]
            if cond.default is not None:
                return cond.default
            raise PromptGraphConfigError(
                f"conditional edge from '{cond.from_node}' on '{cond.on_field}': "
                f"unmatched value '{_bounded_value_repr(value)}' and no default"
            )

        return router

    @staticmethod
    def _join_docs_within_budget(
        docs: list[str], max_chars: int, node_name: str
    ) -> str:
        """Join retrieved documents with the repo's `"\n\n"` separator,
        dropping trailing documents once the budget is exceeded.

        Unlike expert/guidance's rendered-block budgeting (which drops
        lowest-scoring chunks first), a declarative retrieve node has no
        per-document score — store order is the only ordering it has, so
        documents are kept in that order until the budget is spent. This is
        the same character-budget idiom (`max_context_chars`) every other
        retrieval path in the repo already enforces; without it, a payload
        that widens `n_results` can push unbounded document text into the
        next LLM prompt. The budget itself is per-node and payload-settable
        (`Node.max_context_chars`) — the caller passes the resolved value in.
        """
        kept: list[str] = []
        accumulated = 0
        for doc in docs:
            # Cost of appending `doc`: its own chars, plus one more
            # separator once a document already precedes it.
            addition = len(doc) + (len(INTER_BLOCK_SEPARATOR) if kept else 0)
            if accumulated + addition > max_chars:
                if not kept:
                    # A single oversized document still gets through alone —
                    # matches "no answer is fabricated from a failed
                    # retrieval": dropping everything would silently look
                    # like empty retrieval rather than a budget cut.
                    kept.append(doc)
                    accumulated += addition
                break
            kept.append(doc)
            accumulated += addition
        dropped = len(docs) - len(kept)
        if dropped:
            logger.warning(
                "retrieve node '%s' context budget exceeded: kept %d, "
                "dropped %d chunks",
                node_name, len(kept), dropped,
            )
        return INTER_BLOCK_SEPARATOR.join(kept)

    @staticmethod
    def _make_retrieve_node(node: Node, retriever: Callable) -> Callable:
        """Build a LangGraph node function for a declarative retrieve node.

        Template variables are parsed from the two templates themselves
        (`input_variables` is documentation only, never load-bearing). Both
        templates are filled in a SINGLE pass over literal state values —
        member-derived text (e.g. a value a node extracted from the
        conversation) is inserted as data and is never re-interpreted as
        template syntax, whatever characters it contains (FR-011). This is
        the injection-hardening this node exists to get right; do not switch
        to a two-pass or `.format(**state)`-on-member-text implementation.
        """
        formatter = string.Formatter()
        collection_vars = {
            name for _, name, _, _ in formatter.parse(node.collection_template)
            if name
        }
        query_vars = {
            name for _, name, _, _ in formatter.parse(node.query_template)
            if name
        }
        all_vars = collection_vars | query_vars

        async def node_fn(state) -> dict:
            values: dict[str, str] = {}
            for var in all_vars:
                value = PromptGraph._read(state, var, None)
                if value is None:
                    raise PromptGraphConfigError(
                        f"retrieve node '{node.name}': template variable "
                        f"'{var}' has no value in state"
                    )
                values[var] = str(value)

            # Literal single-pass fill: `values` are pre-stringified data,
            # never re-parsed. `str.format_map` performs exactly one
            # substitution pass over the template text — it does not
            # recursively interpret braces inside the substituted values.
            collection = node.collection_template.format_map(values)
            query = node.query_template.format_map(values)

            docs = await retriever(collection, query, node.n_results)
            combined = (
                PromptGraph._join_docs_within_budget(
                    docs, node.max_context_chars, node.name
                )
                if docs else ""
            )
            return {node.output_key: combined}

        return node_fn

    @staticmethod
    def _make_echo_node(node: Node) -> Callable:
        """Build a LangGraph node function for a declarative echo node.

        Copies the current value of ``node.source`` verbatim into the
        flow's result field, with no LLM call. Absent/``None`` echoes as the
        empty string; other falsy values (``0``, ``False``, ``""``) echo as
        their exact string form — no falsy-collapse.
        """

        async def node_fn(state) -> dict:
            value = PromptGraph._read(state, node.source, None)
            return {"result": "" if value is None else str(value)}

        return node_fn

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
                    # Never log `exc` or `raw_text`: the raw LLM response can
                    # be a near-verbatim restatement of member conversation
                    # content (FR-009). Match main.py's error_type-only
                    # redaction idiom — construct name, exception class, and
                    # response length only.
                    logger.warning(
                        "Structured parse failed for node %s: error_type=%s "
                        "response_chars=%d — attempting recovery",
                        node.name, type(exc).__name__, len(raw_text),
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

        async for event in self._compiled.astream(
            initial_state,
            stream_mode=stream_mode,
            config={"recursion_limit": _GRAPH_RECURSION_LIMIT},
        ):
            yield event

    async def invoke(self, initial_state: dict) -> dict:
        """Run the full graph and return final state."""
        if self._compiled is None:
            raise RuntimeError("Graph not compiled — call compile() first")

        result = await self._compiled.ainvoke(
            initial_state, config={"recursion_limit": _GRAPH_RECURSION_LIMIT}
        )
        return self._state_to_dict(result)

    @classmethod
    def from_definition(cls, definition: dict) -> PromptGraph:
        """Build a PromptGraph from a JSON definition.

        Expected format:
        {
            "nodes": [{"name": "...", "input_variables": [...], "prompt": "...", "output": {...}}],
            "edges": [
                {"from": "...", "to": "..."},
                {"from": "...", "on": "...", "map": {"value": "target"}, "default": "target"}
            ],
            "state": {JSON schema},
            "start": "START",
            "end": "END"
        }

        A node's ``type`` (default ``"llm"``) selects ``"retrieve"`` or
        ``"echo"`` fields; edges are split into plain (``from``/``to``) and
        conditional (``from``/``on``/``map``) forms. Every construct is
        validated here at build time — before any LLM call — raising
        :class:`PromptGraphConfigError` naming the offending construct
        (FR-001/FR-002/FR-003 parse side; spec edge cases).
        """
        raw_nodes = definition.get("nodes", [])
        if len(raw_nodes) > _MAX_GRAPH_NODES:
            raise PromptGraphConfigError(
                f"graph definition declares {len(raw_nodes)} nodes, "
                f"exceeding the maximum of {_MAX_GRAPH_NODES}"
            )
        raw_edges = definition.get("edges", [])
        if len(raw_edges) > _MAX_GRAPH_EDGES:
            raise PromptGraphConfigError(
                f"graph definition declares {len(raw_edges)} edges, "
                f"exceeding the maximum of {_MAX_GRAPH_EDGES}"
            )

        nodes: dict[str, Node] = {}
        for node_def in raw_nodes:
            if "name" not in node_def or not node_def["name"]:
                raise PromptGraphConfigError(
                    "node definition is missing a required 'name' field: "
                    f"{node_def!r}"
                )
            node_name = node_def["name"]
            node_type = node_def.get("type", "llm")
            if node_type not in ("llm", "retrieve", "echo"):
                raise PromptGraphConfigError(
                    f"node '{node_name}' declares unknown type '{node_type}'"
                )
            n_results = node_def.get("n_results", 10)
            if node_type == "retrieve":
                if not isinstance(n_results, int) or isinstance(n_results, bool):
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}': n_results "
                        f"{n_results!r} must be an integer, got "
                        f"{type(n_results).__name__}"
                    )
                if not (1 <= n_results <= 50):
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}': "
                        f"n_results {n_results!r} is out of range [1, 50]"
                    )
            max_context_chars = node_def.get(
                "max_context_chars", _RETRIEVE_MAX_CONTEXT_CHARS_DEFAULT
            )
            if node_type == "retrieve":
                if (
                    not isinstance(max_context_chars, int)
                    or isinstance(max_context_chars, bool)
                ):
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}': max_context_chars "
                        f"{max_context_chars!r} must be an integer, got "
                        f"{type(max_context_chars).__name__}"
                    )
                if not (
                    _RETRIEVE_MAX_CONTEXT_CHARS_MIN
                    <= max_context_chars
                    <= _RETRIEVE_MAX_CONTEXT_CHARS_MAX
                ):
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}': max_context_chars "
                        f"{max_context_chars!r} is out of range "
                        f"[{_RETRIEVE_MAX_CONTEXT_CHARS_MIN}, "
                        f"{_RETRIEVE_MAX_CONTEXT_CHARS_MAX}]"
                    )
            collection_template = node_def.get("collection_template", "")
            if node_type == "retrieve":
                if not node_def.get("collection_template"):
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}' requires a non-empty "
                        "'collection_template'"
                    )
                if not node_def.get("query_template"):
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}' requires a non-empty "
                        "'query_template'"
                    )
                # Collection scoping is a tenancy boundary, not a formatting
                # concern: a payload naming any variable other than the
                # server-supplied `bok_id` could otherwise point a query at
                # another tenant's knowledge-store collection. Rejected here,
                # at parse time, before any store query is possible.
                formatter = string.Formatter()
                collection_vars = {
                    name for _, name, _, _ in formatter.parse(collection_template)
                    if name
                }
                disallowed = collection_vars - _ALLOWED_COLLECTION_TEMPLATE_VARS
                if disallowed:
                    raise PromptGraphConfigError(
                        f"retrieve node '{node_name}': "
                        f"collection_template may only reference "
                        f"{sorted(_ALLOWED_COLLECTION_TEMPLATE_VARS)}, "
                        f"found disallowed variable(s) {sorted(disallowed)}"
                    )
            if node_type == "echo" and not node_def.get("source"):
                raise PromptGraphConfigError(
                    f"echo node '{node_name}' requires a non-empty 'source'"
                )
            node = Node(
                name=node_name,
                input_variables=node_def.get("input_variables", []),
                prompt=node_def.get("prompt", ""),
                output_schema=node_def.get("output", {}),
                type=node_type,
                collection_template=collection_template,
                query_template=node_def.get("query_template", ""),
                n_results=n_results,
                output_key=node_def.get("output_key", "knowledge_docs"),
                source=node_def.get("source", ""),
                max_context_chars=max_context_chars,
            )
            nodes[node.name] = node

        known_nodes = set(nodes.keys())

        def _validate_endpoint(name: str, construct: str) -> None:
            if name not in known_nodes and name not in ("START", "END"):
                raise PromptGraphConfigError(
                    f"{construct} names unknown node '{name}'"
                )

        edges: list[Edge] = []
        conditional_edges: list[ConditionalEdge] = []
        conditional_sources: set[str] = set()
        for edge_def in raw_edges:
            if "on" in edge_def or "map" in edge_def:
                from_node = edge_def.get("from", "START")
                if "on" not in edge_def or not edge_def["on"]:
                    raise PromptGraphConfigError(
                        f"conditional edge from '{from_node}' is missing a "
                        "required non-empty 'on' field"
                    )
                if from_node in conditional_sources:
                    raise PromptGraphConfigError(
                        f"conditional edge from '{from_node}': a conditional "
                        "edge from this node is already declared — only one "
                        "conditional edge per source node is allowed"
                    )
                on_field = edge_def["on"]
                raw_map = edge_def.get("map", {})
                if not isinstance(raw_map, dict):
                    raise PromptGraphConfigError(
                        f"conditional edge from '{from_node}': 'map' must "
                        f"be an object, got {type(raw_map).__name__}"
                    )
                for key in raw_map.keys():
                    if not isinstance(key, str):
                        raise PromptGraphConfigError(
                            f"conditional edge from '{from_node}': 'map' key "
                            f"{key!r} must be a string"
                        )
                for target in raw_map.values():
                    if not isinstance(target, str):
                        raise PromptGraphConfigError(
                            f"conditional edge from '{from_node}': 'map' "
                            f"target {target!r} must be a string node name"
                        )
                path_map = {str(k).lower(): v for k, v in raw_map.items()}
                default = edge_def.get("default")
                _validate_endpoint(from_node, "conditional edge 'from'")
                for target in path_map.values():
                    _validate_endpoint(target, "conditional edge 'map' target")
                if default is not None:
                    _validate_endpoint(default, "conditional edge 'default'")
                conditional_sources.add(from_node)
                conditional_edges.append(ConditionalEdge(
                    from_node=from_node,
                    on_field=on_field,
                    path_map=path_map,
                    default=default,
                ))
            else:
                from_node = edge_def.get("from", "START")
                to_node = edge_def.get("to", "END")
                _validate_endpoint(from_node, "edge 'from'")
                _validate_endpoint(to_node, "edge 'to'")
                edges.append(Edge(from_node=from_node, to_node=to_node))

        return cls(
            nodes=nodes,
            edges=edges,
            state_schema=definition.get("state"),
            start_node=definition.get("start", "START"),
            end_node=definition.get("end", "END"),
            conditional_edges=conditional_edges,
        )
