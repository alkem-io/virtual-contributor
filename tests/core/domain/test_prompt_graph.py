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


# ---------------------------------------------------------------------------
# _normalize_schema
# ---------------------------------------------------------------------------


class TestNormalizeSchema:
    def test_list_properties_to_dict(self):
        schema = {
            "properties": [
                {"name": "field1", "type": "string"},
                {"name": "field2", "type": "integer"},
            ]
        }
        result = PromptGraph._normalize_schema(schema)
        assert isinstance(result["properties"], dict)
        assert "field1" in result["properties"]
        assert "field2" in result["properties"]
        assert result["properties"]["field1"]["type"] == "string"
        assert result["properties"]["field2"]["type"] == "integer"
        assert "field1" in result["required"]
        assert "field2" in result["required"]
        assert result["type"] == "object"

    def test_optional_fields_made_nullable(self):
        schema = {
            "properties": [
                {"name": "opt", "type": "string", "optional": True},
            ]
        }
        result = PromptGraph._normalize_schema(schema)
        prop = result["properties"]["opt"]
        assert prop["type"] == ["string", "null"]
        assert prop["default"] is None

    def test_required_fields_in_required_list(self):
        schema = {
            "properties": [
                {"name": "req", "type": "string"},
                {"name": "opt", "type": "string", "optional": True},
            ]
        }
        result = PromptGraph._normalize_schema(schema)
        assert "req" in result["required"]
        assert "opt" not in result["required"]

    def test_dict_properties_passthrough(self):
        schema = {
            "properties": {
                "x": {"type": "string"},
            }
        }
        result = PromptGraph._normalize_schema(schema)
        assert isinstance(result["properties"], dict)
        assert "x" in result["properties"]

    def test_nested_object_normalization(self):
        schema = {
            "properties": [
                {
                    "name": "nested",
                    "type": "object",
                    "properties": [
                        {"name": "inner", "type": "string"},
                    ],
                },
            ]
        }
        result = PromptGraph._normalize_schema(schema)
        nested = result["properties"]["nested"]
        assert isinstance(nested["properties"], dict)
        assert "inner" in nested["properties"]

    def test_array_items_normalized(self):
        schema = {
            "items": {
                "properties": [
                    {"name": "val", "type": "integer"},
                ]
            }
        }
        result = PromptGraph._normalize_schema(schema)
        items = result["items"]
        assert isinstance(items["properties"], dict)
        assert "val" in items["properties"]

    def test_combinators_normalized(self):
        schema = {
            "anyOf": [
                {
                    "properties": [
                        {"name": "a", "type": "string"},
                    ]
                }
            ]
        }
        result = PromptGraph._normalize_schema(schema)
        variant = result["anyOf"][0]
        assert isinstance(variant["properties"], dict)
        assert "a" in variant["properties"]

    def test_none_input_returns_none(self):
        assert PromptGraph._normalize_schema(None) is None

    def test_non_dict_input_returns_input(self):
        assert PromptGraph._normalize_schema("not a dict") == "not a dict"


# ---------------------------------------------------------------------------
# _make_nullable
# ---------------------------------------------------------------------------


class TestMakeNullable:
    def test_string_type_widened(self):
        result = PromptGraph._make_nullable({"type": "string"})
        assert result["type"] == ["string", "null"]
        assert result["default"] is None

    def test_list_type_widened(self):
        result = PromptGraph._make_nullable({"type": ["string", "integer"]})
        assert result["type"] == ["string", "integer", "null"]
        assert result["default"] is None

    def test_already_nullable_unchanged(self):
        result = PromptGraph._make_nullable({"type": ["string", "null"]})
        assert result["type"] == ["string", "null"]
        assert result["type"].count("null") == 1

    def test_non_dict_passthrough(self):
        assert PromptGraph._make_nullable("not a dict") == "not a dict"

    def test_existing_default_preserved(self):
        result = PromptGraph._make_nullable({"type": "string", "default": "hello"})
        assert result["default"] == "hello"


# ---------------------------------------------------------------------------
# _recover_fields
# ---------------------------------------------------------------------------


class TestRecoverFields:
    def test_recover_nested_fields(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str

        raw = '{"result": {"answer": "hello"}}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["answer"] == "hello"

    def test_recover_text_alias(self):
        from pydantic import BaseModel

        class SummaryModel(BaseModel):
            summary: str

        raw = '{"summary_text": "hello"}'
        result = PromptGraph._recover_fields(raw, SummaryModel)
        assert result is not None
        assert result["summary"] == "hello"

    def test_missing_required_fields_returns_none(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str

        raw = '{"unrelated": "stuff"}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is None

    def test_non_json_returns_none(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str

        result = PromptGraph._recover_fields("This is not JSON", AnswerModel)
        assert result is None

    def test_null_values_for_optional_fields(self):
        from pydantic import BaseModel

        class OptionalModel(BaseModel):
            answer: str
            detail: str | None = None

        raw = '{"answer": "hi", "detail": null}'
        result = PromptGraph._recover_fields(raw, OptionalModel)
        assert result is not None
        assert result["answer"] == "hi"
        assert result["detail"] is None

    def test_prefers_non_null_over_null(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str

        raw = '{"answer": null, "nested": {"answer": "found"}}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["answer"] == "found"

    def test_fills_missing_str_with_empty_string(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str
            answer_language: str

        # Classic Mistral-Small regression: drops the auxiliary field.
        raw = '{"answer": "Hi there"}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["answer"] == "Hi there"
        assert result["answer_language"] == ""

    def test_fills_missing_dict_with_empty_dict(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str
            source_scores: dict

        raw = '{"answer": "Hi"}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["source_scores"] == {}

    def test_fills_missing_list_with_empty_list(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str
            tags: list[str]

        raw = '{"answer": "Hi"}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["tags"] == []

    def test_fills_missing_bool_with_false(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str
            requires_followup: bool

        raw = '{"answer": "Hi"}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["requires_followup"] is False

    def test_fills_missing_int_with_zero(self):
        from pydantic import BaseModel

        class AnswerModel(BaseModel):
            answer: str
            confidence: int

        raw = '{"answer": "Hi"}'
        result = PromptGraph._recover_fields(raw, AnswerModel)
        assert result is not None
        assert result["confidence"] == 0

    def test_real_world_answer_response_shape(self):
        """Reproduces the Mistral-Small / oasisbot query failure."""
        from pydantic import BaseModel

        class AnswerResponse(BaseModel):
            knowledge_answer: str
            answer_language: str
            source_scores: dict

        raw = (
            '{"knowledge_answer": "Maria\'s phone number is +359 88 6111122.",'
            ' "source_scores": {"0": 7, "1": 0, "2": 0, "3": 0, "4": 0}}'
        )
        result = PromptGraph._recover_fields(raw, AnswerResponse)
        assert result is not None
        assert "Maria" in result["knowledge_answer"]
        assert result["source_scores"] == {"0": 7, "1": 0, "2": 0, "3": 0, "4": 0}
        assert result["answer_language"] == ""  # filled default, message flows


# ---------------------------------------------------------------------------
# _state_to_dict and wrappers
# ---------------------------------------------------------------------------


class TestStateToDictAndWrappers:
    def test_dict_passthrough(self):
        d = {"a": 1}
        assert PromptGraph._state_to_dict(d) == {"a": 1}

    def test_pydantic_model_converted(self):
        from pydantic import BaseModel

        class SimpleModel(BaseModel):
            x: int = 0
            y: str = "hi"

        instance = SimpleModel(x=42, y="hello")
        result = PromptGraph._state_to_dict(instance)
        assert isinstance(result, dict)
        assert result["x"] == 42
        assert result["y"] == "hello"

    def test_build_state_model_with_list_schema(self):
        schema = {
            "properties": [
                {"name": "question", "type": "string"},
                {"name": "answer", "type": "string", "optional": True},
            ]
        }
        model = PromptGraph._build_state_model(schema)
        assert model is not None
        instance = model()
        dumped = instance.model_dump()
        assert "question" in dumped
        assert "answer" in dumped

    def test_build_output_model_normalizes_schema(self):
        node = Node(
            name="test_node",
            input_variables=["q"],
            prompt="Answer: {q}",
            output_schema={
                "properties": [
                    {"name": "result", "type": "string"},
                ]
            },
        )
        model = PromptGraph._build_output_model(node)
        assert model is not None
        # Verify the model can be used to validate data
        instance = model(result="hello")
        assert instance.model_dump()["result"] == "hello"
