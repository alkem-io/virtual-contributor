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


#: Shared ordered event log the scripted chat model and the store double
#: both append to, so a test can assert interleaving (extract before store
#: query before refine) rather than just a call count. Populated per-test
#: via the `_reset_scripted_model`/store fixtures below.
EVENT_LOG: list[str] = []


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
        EVENT_LOG.append(f"llm:{len(type(self).calls)}")
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
    EVENT_LOG.clear()
    yield
    ScriptedChatModel.responses = []
    ScriptedChatModel.calls = []
    EVENT_LOG.clear()


class LoggingKnowledgeStore(MockKnowledgeStorePort):
    """`MockKnowledgeStorePort` plus an append to the shared `EVENT_LOG`.

    Lets a test assert the real extract -> retrieve -> refine interleaving
    against the scripted LLM's own log entries, instead of only a call
    count (which can't distinguish "ran in order" from "ran out of
    order but the same number of times").
    """

    async def query(self, collection, query_texts, n_results=10, where=None):
        EVENT_LOG.append(f"store:{len(self.query_calls) + 1}")
        return await super().query(collection, query_texts, n_results=n_results, where=where)


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
        store = LoggingKnowledgeStore()
        marker_doc = "LS: 1-2-4-All is a facilitation technique."
        store.collections["ls-101-knowledge"] = [
            {"document": marker_doc, "metadata": {"embeddingType": "chunk"}, "id": "1"},
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
        # Grounding: the store's marker document must actually reach the
        # generate node's LLM prompt — a broken `output_key` (LangGraph
        # silently drops an undeclared state key) or a mis-wired retrieve
        # node would still pass every assertion above while `generate`
        # receives empty `{knowledge_docs}` (R-4, confident ungrounded
        # designs).
        final_call_content = ScriptedChatModel.calls[-1][0].content
        assert marker_doc in final_call_content
        # Ordering: the store query ran strictly before the final (generate)
        # LLM call, not merely "some LLM call ran and some store call ran".
        assert EVENT_LOG.index("store:1") < EVENT_LOG.index(f"llm:{len(ScriptedChatModel.calls)}")


class TestWorkshopPayloadRefine:
    async def test_us2_as3_refine_path_extracts_then_retrieves_then_revises(self):
        payload = _load_shipped_payload()
        store = LoggingKnowledgeStore()
        marker_doc = "LS: Impromptu Networking for onboarding."
        store.collections["ls-101-knowledge"] = [
            {"document": marker_doc, "metadata": {"embeddingType": "chunk"}, "id": "1"},
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
        assert len(ScriptedChatModel.calls) == 4
        assert len(store.query_calls) == 1
        # Ordering: the shared event log — appended to by BOTH the scripted
        # LLM and the store double — pins the true interleaving. "llm:3" is
        # `extract`'s call (check_input, analyse_last_message, extract are
        # the first three LLM nodes on this path); it must precede the sole
        # store query, which must precede "llm:4" (`refine`). A payload
        # rewired to retrieve before extracting, or to retrieve after
        # refining, breaks this even though the call *counts* stay 4 and 1.
        assert EVENT_LOG == ["llm:1", "llm:2", "llm:3", "store:1", "llm:4"]
        # Grounding: the retrieved marker document must actually reach the
        # refine node's LLM prompt, not just get queried and discarded.
        refine_call_content = ScriptedChatModel.calls[-1][0].content
        assert marker_doc in refine_call_content


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


class TestWorkshopPayloadSlotRecovery:
    async def test_complete_true_omitted_slot_recovers_default_one_store_query(self):
        """A `complete: true` model reply that drops one of the five
        required slots must not raise `PromptGraphConfigError` inside
        `_make_retrieve_node` — the payload schema requires every slot, so
        the parse failure lands in `_recover_fields`, which fills the
        missing slot with its type default, and the flow completes with
        exactly ONE store query (not retried across 3 RabbitMQ attempts)."""
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        store.collections["ls-101-knowledge"] = [
            {"document": "LS: 1-2-4-All is a facilitation technique.", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            # `purpose` is entirely omitted, not merely null.
            json.dumps({
                "role": "facilitator", "duration": "2 hours",
                "workshop_type": "in-person", "audience_size": 20,
                "question": "unused", "complete": True,
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

    async def test_complete_true_explicit_null_slot_recovers_default_one_store_query(self):
        """R-3's actual reachable failure class: the model returns
        `complete: true` alongside an EXPLICIT `null` for a slot (not
        merely omitting the key — the schema fully permits an internally
        consistent reply where the model claims completeness but leaves a
        slot null). Before batch2's schema tightening, this parsed cleanly
        with the null intact and reached `_make_retrieve_node`'s template
        fill, raising `PromptGraphConfigError` there — burning the LLM
        calls already made and repeating on every RabbitMQ retry, with the
        member getting only the standard error response instead of a
        design or a clarifying question. Now that every slot is required
        AND non-nullable, a literal JSON `null` also fails
        `PydanticOutputParser.parse()` and lands in `_recover_fields`,
        which fills the type default — same safe path as an omitted key."""
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        store.collections["ls-101-knowledge"] = [
            {"document": "LS: 1-2-4-All is a facilitation technique.", "metadata": {"embeddingType": "chunk"}, "id": "1"},
        ]
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            # `duration` is present but explicitly null, not omitted.
            json.dumps({
                "role": "facilitator", "duration": None,
                "workshop_type": "in-person", "purpose": "team building",
                "audience_size": 20, "question": "unused", "complete": True,
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

    async def test_complete_false_omitted_question_still_answers_member(self):
        """A `complete: false` reply that renames the canonical `question`
        key (e.g. a terse model writing `question_text` instead) previously
        parsed cleanly against the old nullable/not-required schema — the
        canonical field landed as `None`, silently, with nothing logged, and
        the member got a blank reply despite the model having written a
        real clarifying question. Now that `question` is required, the
        strict parse fails and best-effort recovery's `_text`-alias walk
        finds the model's actual text and the member gets it verbatim."""
        payload = _load_shipped_payload()
        store = MockKnowledgeStorePort()
        plugin = _make_plugin(store)
        ScriptedChatModel.responses = [
            json.dumps({
                "role": None, "duration": None, "workshop_type": None,
                "purpose": None, "audience_size": None,
                "complete": False,
                # Model wrote the clarifying text under a near-miss key
                # instead of the canonical `question` field.
                "question_text": "How long should the workshop be?",
            }),
        ]
        event = make_input(
            message="I want to run a workshop.",
            promptGraph=payload,
            bodyOfKnowledgeID="ls-101",
        )
        result = await plugin.handle(event)
        assert isinstance(result, Response)
        assert result.result == "How long should the workshop be?"
        assert store.query_calls == []


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
