"""Guidance: gating, the anaphora guard, and the flag-off invariant.

Guidance already condensed on every turn with history, so the change here is
subtraction — the trivial turn stops paying for a call it does not need.
"""

from __future__ import annotations

import pytest

from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, make_input
from tests.plugins._rewrite_fixtures import (
    ANAPHORIC,
    CONVERSATIONAL,
    HISTORY,
    RESOLVED,
    CountingLLM,
    SkipConversational,
    SkipEverySimpleQuery,
)


def _plugin(llm, **kw) -> GuidancePlugin:
    return GuidancePlugin(llm=llm, knowledge_store=MockKnowledgeStorePort(), **kw)


class TestConversationalTurnsSkipTheRewrite:
    @pytest.mark.parametrize("message", CONVERSATIONAL)
    async def test_conversational_turn_makes_no_rewrite_call(
        self, message: str
    ) -> None:
        llm = CountingLLM()
        await _plugin(llm, rewrite_policy=SkipConversational()).handle(
            make_input(message=message, history=HISTORY)
        )
        assert llm.n == 1, f"{message!r} paid for a rewrite it did not need"

    async def test_conversational_cost_equals_the_no_history_baseline(self) -> None:
        """The saving is real, not merely reordered."""
        baseline = CountingLLM()
        await _plugin(baseline).handle(make_input(message="What is a space?"))

        gated = CountingLLM()
        await _plugin(gated, rewrite_policy=SkipConversational()).handle(
            make_input(message="thanks!", history=HISTORY)
        )
        assert gated.n == baseline.n


class TestSubstantiveTurnsStillRewriteExactlyOnce:
    async def test_substantive_turn_rewrites_once(self) -> None:
        llm = CountingLLM()
        await _plugin(llm, rewrite_policy=SkipConversational()).handle(
            make_input(message="How is governance decided?", history=HISTORY)
        )
        assert llm.n == 2, "expected exactly one rewrite plus one answer"

    async def test_substantive_turn_is_no_more_expensive_than_develop(self) -> None:
        """Guards against 'fixing' latency by dropping the rewrite entirely."""
        ungated = CountingLLM()
        await _plugin(ungated).handle(
            make_input(message="How is governance decided?", history=HISTORY)
        )
        gated = CountingLLM()
        await _plugin(gated, rewrite_policy=SkipConversational()).handle(
            make_input(message="How is governance decided?", history=HISTORY)
        )
        assert gated.n == ungated.n == 2


class TestAnaphoricFollowUpsAlwaysRewrite:
    """The most important behaviour in the feature.

    The story recommends skipping "simple" queries. Each of these classifies
    SIMPLE or lower yet is meaningless without the preceding turn, so skipping
    them sends an unresolved fragment to the vector store — silently, with no
    error and no way for anyone to notice from the outside.
    """

    @pytest.mark.parametrize("message", ANAPHORIC)
    async def test_anaphor_is_rewritten(self, message: str) -> None:
        llm = CountingLLM()
        await _plugin(llm, rewrite_policy=SkipConversational()).handle(
            make_input(message=message, history=HISTORY)
        )
        assert llm.n == 2, f"{message!r} was sent to retrieval unresolved"

    async def test_the_recommended_policy_would_break_these(self) -> None:
        """Records *why* the narrower gate was chosen, by demonstration.

        Not a guard on shipped behaviour — a guard on the reasoning, so a later
        'optimisation' back to skip-SIMPLE has to delete this test knowingly.
        """
        broken = 0
        for message in ANAPHORIC:
            llm = CountingLLM()
            await _plugin(llm, rewrite_policy=SkipEverySimpleQuery()).handle(
                make_input(message=message, history=HISTORY)
            )
            if llm.n == 1:
                broken += 1
        assert broken >= 8, (
            "the story's recommended policy is supposed to break most of these; "
            "if it no longer does, re-derive the gate boundary"
        )


class TestFlagDisabledMatchesDevelop:
    async def test_flag_disabled_rewrites_every_turn_with_history(self) -> None:
        """No policy == gating off. Behaviour matches develop exactly."""
        for message in CONVERSATIONAL[:2] + ANAPHORIC[:2]:
            llm = CountingLLM()
            await _plugin(llm).handle(make_input(message=message, history=HISTORY))
            assert llm.n == 2, f"{message!r} skipped with gating disabled"

    async def test_flag_disabled_never_rewrites_without_history(self) -> None:
        llm = CountingLLM()
        await _plugin(llm).handle(make_input(message="What is a space?"))
        assert llm.n == 1


class TestGuidanceStillAnswers:
    async def test_the_resolved_question_reaches_retrieval(self) -> None:
        store = MockKnowledgeStorePort()
        await GuidancePlugin(llm=CountingLLM(), knowledge_store=store).handle(
            make_input(message="and the other one?", history=HISTORY)
        )
        assert store.query_calls[0][1] == [RESOLVED]

    async def test_a_response_is_still_produced(self) -> None:
        response = await _plugin(CountingLLM()).handle(
            make_input(message="and the other one?", history=HISTORY)
        )
        assert response.result
