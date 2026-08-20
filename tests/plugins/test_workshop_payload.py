"""E2E tests — shipped workshop-design payload executed via GenericPlugin (FR-008, US2).

Loads the SHIPPED artifact itself (``docs/prompt-graphs/workshop-design.json``)
via ``json.load`` — never a copy embedded in this file (FR-008/R-5).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import pytest

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from core.events.response import Response
from plugins.generic.plugin import GenericPlugin
from tests.conftest import MockKnowledgeStorePort, make_input

PAYLOAD_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "prompt-graphs" / "workshop-design.json"
)


def _load_shipped_payload() -> dict:
    with PAYLOAD_PATH.open() as f:
        return json.load(f)


class ScriptedChatModel(BaseChatModel):
    """Real LangChain chat model returning queued responses in call order.

    Real (not a mock port) because LLM graph nodes pipe the prompt template
    through an LCEL ``Runnable`` — this is the same double shape used by
    ``tests/plugins/test_expert_two_stage.py``.
    """

    responses: ClassVar[list[str]] = []
    calls: ClassVar[list[list[BaseMessage]]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted-workshop"

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager: Any = None, **kwargs: Any,
    ) -> ChatResult:
        type(self).calls.append(messages)
        content = type(self).responses.pop(0)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])


class _LLMAdapter:
    """Adapts a BaseChatModel to the shape GenericPlugin's `_llm` needs.

    `PromptGraph._make_chain_node` reads `llm._llm` when present, falling
    back to `llm` itself — this adapter carries the real chat model under
    `_llm` (matching `LangChainLLMAdapter`'s shape) so both the graph path
    and any direct-call fallback (unused here) behave like production.
    """

    def __init__(self, chat_model: BaseChatModel) -> None:
        self._llm = chat_model

    async def invoke(self, messages: list[dict], **kwargs):  # pragma: no cover
        raise AssertionError("direct invoke should not be used on the graph path")


@pytest.fixture(autouse=True)
def _reset_scripted_model():
    ScriptedChatModel.responses = []
    ScriptedChatModel.calls = []
    yield
    ScriptedChatModel.responses = []
    ScriptedChatModel.calls = []


def _make_plugin(store: MockKnowledgeStorePort | None = None) -> GenericPlugin:
    chat_model = ScriptedChatModel()
    llm = _LLMAdapter(chat_model)
    return GenericPlugin(llm=llm, knowledge_store=store)


class TestWorkshopPayloadShipped:
    def test_us2_as4_loads_shipped_file_not_a_copy(self):
        payload = _load_shipped_payload()
        assert payload["nodes"][0]["name"] == "check_input"
        assert any(n.get("type") == "retrieve" for n in payload["nodes"])
        assert any(n.get("type") == "echo" for n in payload["nodes"])


class TestWorkshopPayloadClarify:
    async def test_us2_as1_incomplete_returns_clarifying_question_no_retrieval(self):
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            json.dumps({
                "role": None, "duration": None, "workshop_type": None,
                "purpose": None, "audience_size": None,
                "question": "What role will you play, and how long is the workshop?",
                "complete": False,
            }),
        ]
        event = make_input(
            message="I want to run a workshop.",
            promptGraph=payload,
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "What role will you play, and how long is the workshop?"
        assert store.query_calls == []
        assert len(ScriptedChatModel.calls) == 1


class TestWorkshopPayloadGenerate:
    async def test_us2_as2_generate_path_retrieves_and_returns_design(self):
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        store.collections["ls-101-knowledge"] = [
            {"document": "LS: 1-2-4-All is a facilitation technique.", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            json.dumps({
                "role": "facilitator", "duration": "2 hours",
                "workshop_type": "in-person", "purpose": "team building",
                "audience_size": 20, "question": None, "complete": True,
            }),
            json.dumps({"action": "generate"}),
            "## Workshop Design\n\nUse 1-2-4-All to kick things off.",
        ]
        event = make_input(
            message="Generate a workshop design for me.",
            promptGraph=payload,
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "## Workshop Design\n\nUse 1-2-4-All to kick things off."
        assert len(store.query_calls) == 1
        collection, query_texts, n_results, where = store.query_calls[0]
        assert collection == "ls-101-knowledge"
        query_text = query_texts[0]
        for slot in ("facilitator", "2 hours", "in-person", "team building", "20"):
            assert slot in query_text
        assert n_results == 10


class TestWorkshopPayloadRefine:
    async def test_us2_as3_refine_path_extracts_then_retrieves_then_revises(self):
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        store.collections["ls-101-knowledge"] = [
            {"document": "LS: Impromptu Networking for onboarding.", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            json.dumps({
                "role": "facilitator", "duration": "1 day",
                "workshop_type": "online", "purpose": "onboarding",
                "audience_size": 10, "question": None, "complete": True,
            }),
            json.dumps({"action": "refine"}),
            json.dumps({"current": "## Old Design\n\nOriginal content."}),
            "## Revised Design\n\nUpdated content with the requested change.",
        ]
        event = make_input(
            message="Please make it shorter.",
            promptGraph=payload,
            bodyOfKnowledgeID="ls-101",
            history=[
                {"content": "Generate a workshop design for me.", "role": "human"},
                {"content": "## Old Design\n\nOriginal content.", "role": "assistant"},
            ],
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "## Revised Design\n\nUpdated content with the requested change."
        # extract (call 3) ran before the store query, which ran before
        # refine (call 4) — call order proves it since extract is the only
        # node between analyse and the store query.
        assert len(ScriptedChatModel.calls) == 4
        assert len(store.query_calls) == 1


class TestStructuredParseFailureLogging:
    async def test_parse_failure_never_logs_raw_response_only_error_type_and_length(
        self, caplog
    ):
        """A structured-output parse failure must log only the exception
        class, node name, and response length — never the raw LLM response
        text, which can be a near-verbatim restatement of member
        conversation content."""
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        plugin = _make_plugin(store)
        sentinel = "Jane Doe, jane@acme.example, our Q3 layoff planning session"
        # No JSON object at all: fails PydanticOutputParser.parse() AND the
        # best-effort `_recover_fields` fallback, so the exception re-raises
        # after the warning is logged.
        ScriptedChatModel.responses = [
            f"Here is the workshop design from the conversation: {sentinel} "
            "— no structured output was produced."
        ]
        event = make_input(
            message="I want to run a workshop.",
            promptGraph=payload,
            bodyOfKnowledgeID="ls-101",
        )
        with caplog.at_level(logging.WARNING):
            with pytest.raises(Exception):
                await plugin.handle(event)
        log_text = "\n".join(record.getMessage() for record in caplog.records)
        assert sentinel not in log_text
        assert "error_type=" in log_text
        assert "response_chars=" in log_text


class TestWorkshopPayloadRecovery:
    async def test_missing_complete_field_recovers_to_false_clarify_path(self):
        """RK-2: a check_input reply missing the required `complete` field
        recovers via `_recover_fields` to `complete=false` (the safe
        direction), routing to clarify rather than crashing."""
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            json.dumps({
                "role": "facilitator", "duration": None, "workshop_type": None,
                "purpose": None, "audience_size": None,
                "question": "How long should the workshop be?",
                # `complete` deliberately omitted.
            }),
        ]
        event = make_input(
            message="I want a workshop with a facilitator.",
            promptGraph=payload,
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        # `complete` was recovered as False (the safe default) — routes to
        # `ask`, which echoes the question the LLM did provide, verbatim.
        assert result.result == "How long should the workshop be?"
        assert store.query_calls == []
