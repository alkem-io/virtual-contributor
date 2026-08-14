"""Generic: gating, and the two live defects this feature fixes.

Generic has no retrieval, so the rewrite only shapes what the LLM is asked.
The failure and validation behaviour is identical to guidance's and is asserted
here too — the two plugins condense independently, and a fix applied to one is
worth nothing to the other.
"""

from __future__ import annotations

import pytest

from plugins.generic.plugin import GenericPlugin
from tests.conftest import MockLLMPort, make_input
from tests.plugins._rewrite_fixtures import (
    ANAPHORIC,
    CONVERSATIONAL,
    HISTORY,
    CountingLLM,
    SkipConversational,
)


class TestConversationalTurnsSkipTheRewrite:
    @pytest.mark.parametrize("message", CONVERSATIONAL)
    async def test_conversational_turn_makes_no_rewrite_call(
        self, message: str
    ) -> None:
        llm = CountingLLM()
        await GenericPlugin(llm=llm, rewrite_policy=SkipConversational()).handle(
            make_input(message=message, history=HISTORY)
        )
        assert llm.n == 1, f"{message!r} paid for a rewrite it did not need"

    async def test_conversational_cost_equals_the_no_history_baseline(self) -> None:
        baseline = CountingLLM()
        await GenericPlugin(llm=baseline).handle(make_input(message="What is a space?"))
        gated = CountingLLM()
        await GenericPlugin(llm=gated, rewrite_policy=SkipConversational()).handle(
            make_input(message="ok", history=HISTORY)
        )
        assert gated.n == baseline.n


class TestSubstantiveTurnsStillRewriteExactlyOnce:
    async def test_substantive_turn_rewrites_once(self) -> None:
        llm = CountingLLM()
        await GenericPlugin(llm=llm, rewrite_policy=SkipConversational()).handle(
            make_input(message="How is governance decided?", history=HISTORY)
        )
        assert llm.n == 2

    @pytest.mark.parametrize("message", ANAPHORIC[:4])
    async def test_substantive_anaphor_still_rewrites(self, message: str) -> None:
        llm = CountingLLM()
        await GenericPlugin(llm=llm, rewrite_policy=SkipConversational()).handle(
            make_input(message=message, history=HISTORY)
        )
        assert llm.n == 2


class TestRewriteFailureNeverFailsTheRequest:
    """N-2 — on develop, one raised exception from the condense call aborts the
    entire request, even though the original message was a usable query."""

    async def test_failure_still_produces_an_answer(self) -> None:
        class _FailFirst(MockLLMPort):
            n = 0

            async def invoke(self, messages, **kw):  # type: ignore[override]
                _FailFirst.n += 1
                if _FailFirst.n == 1:
                    raise RuntimeError("condense died")
                return "the real answer"

        _FailFirst.n = 0
        response = await GenericPlugin(llm=_FailFirst(response="x")).handle(
            make_input(message="and the other one?", history=HISTORY)
        )
        assert response.result == "the real answer"

    async def test_a_failure_after_the_rewrite_still_propagates(self) -> None:
        """Only the *rewrite* is made non-fatal. A broken answer call is still
        a broken request — swallowing that would hide a real outage."""

        class _FailSecond(MockLLMPort):
            n = 0

            async def invoke(self, messages, **kw):  # type: ignore[override]
                _FailSecond.n += 1
                if _FailSecond.n == 1:
                    return "resolved question"
                raise RuntimeError("LLM unavailable")

        _FailSecond.n = 0
        with pytest.raises(RuntimeError, match="LLM unavailable"):
            await GenericPlugin(llm=_FailSecond(response="x")).handle(
                make_input(message="and the other one?", history=HISTORY)
            )


class TestDegenerateRewriteOutputFallsBack:
    """N-1 — on develop the condense result is assigned verbatim, so an empty
    string or a refusal becomes the question the model is asked."""

    @pytest.mark.parametrize("bad", ["", "   ", "\n", None, 42, ["a"]])
    async def test_unusable_output_falls_back_to_the_original(
        self, bad: object
    ) -> None:
        class _BadFirst(MockLLMPort):
            n = 0
            seen: list = []

            async def invoke(self, messages, **kw):  # type: ignore[override]
                _BadFirst.n += 1
                if _BadFirst.n == 1:
                    return bad
                _BadFirst.seen = messages
                return "an answer"

        _BadFirst.n = 0
        _BadFirst.seen = []
        await GenericPlugin(llm=_BadFirst(response="x")).handle(
            make_input(message="and the other one?", history=HISTORY)
        )
        asked = " ".join(str(m.get("content", "")) for m in _BadFirst.seen)
        assert "and the other one?" in asked


class TestFlagDisabledMatchesDevelop:
    async def test_flag_disabled_rewrites_every_turn_with_history(self) -> None:
        for message in CONVERSATIONAL[:2] + ANAPHORIC[:2]:
            llm = CountingLLM()
            await GenericPlugin(llm=llm).handle(
                make_input(message=message, history=HISTORY)
            )
            assert llm.n == 2

    async def test_flag_disabled_never_rewrites_without_history(self) -> None:
        llm = CountingLLM()
        await GenericPlugin(llm=llm).handle(make_input(message="What is a space?"))
        assert llm.n == 1
