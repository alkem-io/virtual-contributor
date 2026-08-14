"""The rewrite gate, its output validation, and its fallback.

Two of the three behaviours here are fixes for live defects on develop: the
condense output is used verbatim however malformed (N-1), and one raised
exception from that call aborts the whole request (N-2). The third is the gate
itself, which must be *narrow* — see `TestTheGateIsNarrow`.
"""

from __future__ import annotations

import logging

import pytest

from core.domain.query_rewrite import (
    DEFAULT_MAX_EXPANSION_RATIO,
    DEFAULT_MAX_HISTORY_TURNS,
    MIN_REWRITE_ALLOWANCE,
    RewritePolicy,
    recent_history,
    rewrite_query,
    should_rewrite,
    validate_rewrite,
)

ORIGINAL = "What is the governance model for subspaces?"


class _SkipEverything:
    """A policy that always skips."""

    def should_skip_rewrite(self, message: str) -> bool:
        return True


class _SkipNothing:
    """A policy that never skips."""

    def should_skip_rewrite(self, message: str) -> bool:
        return False


class _SkipShort:
    """A third policy, behaving differently from both of the above."""

    def should_skip_rewrite(self, message: str) -> bool:
        return len(message.split()) <= 2


class _FakeLLM:
    def __init__(self, response: object) -> None:
        self._response = response
        self.calls: list[list[dict]] = []

    async def invoke(self, messages: list[dict]) -> object:
        self.calls.append(messages)
        return self._response


class _RaisingLLM:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def invoke(self, messages: list[dict]) -> object:
        raise self._exc


class TestValidateRejectsUnusableRewrites:
    """N-1 — today whatever the model returns becomes the retrieval query."""

    @pytest.mark.parametrize("candidate", ["", "   ", "\n\t "])
    def test_validate_falls_back_on_an_empty_rewrite(self, candidate: str) -> None:
        """An empty query searches the vector store for nothing at all."""
        assert validate_rewrite(candidate, ORIGINAL) == ORIGINAL

    @pytest.mark.parametrize("candidate", [None, 42, ["a", "b"], {"q": "x"}, object()])
    def test_validate_falls_back_on_a_non_string(self, candidate: object) -> None:
        """This function is the boundary that makes adapter output a `str`."""
        assert validate_rewrite(candidate, ORIGINAL) == ORIGINAL

    def test_validate_falls_back_on_an_over_long_rewrite(self) -> None:
        """A model that starts explaining instead of rewriting.

        Its prose would otherwise become the vector-store query.
        """
        essay = "x" * int(len(ORIGINAL) * DEFAULT_MAX_EXPANSION_RATIO + 1)
        assert validate_rewrite(essay, ORIGINAL) == ORIGINAL

    def test_validate_keeps_a_rewrite_exactly_at_the_limit(self) -> None:
        """The boundary is inclusive — only *longer* than the ratio is rejected."""
        at_limit = "x" * int(len(ORIGINAL) * DEFAULT_MAX_EXPANSION_RATIO)
        assert validate_rewrite(at_limit, ORIGINAL) == at_limit

    def test_validate_passes_a_normal_rewrite_through(self) -> None:
        rewritten = "What is the governance model for Alkemio subspaces?"
        assert validate_rewrite(rewritten, ORIGINAL) == rewritten

    def test_validate_strips_surrounding_whitespace(self) -> None:
        assert validate_rewrite("  a standalone question  ", ORIGINAL) == (
            "a standalone question"
        )

    def test_validate_tolerates_an_empty_original(self) -> None:
        """`max(len(original), 1)` — an empty original must not divide by zero."""
        assert validate_rewrite("something", "") == "something"


class TestFailureNeverCostsTheAnswer:
    """N-2 — today one raised exception aborts the entire request."""

    async def test_rewrite_returns_the_original_when_the_llm_raises(self) -> None:
        result = await rewrite_query(
            _RaisingLLM(RuntimeError("LLM unavailable")), [{"role": "human"}], ORIGINAL
        )
        assert result == ORIGINAL

    async def test_a_rewrite_failure_is_logged_without_the_conversation(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The exception message can quote the prompt, which carries the
        member's conversation; logs reach central logging."""
        secret = "members: alice@example.com asked about payroll"
        with caplog.at_level(logging.WARNING, logger="core.domain.query_rewrite"):
            await rewrite_query(
                _RaisingLLM(RuntimeError(secret)), [{"role": "human"}], ORIGINAL
            )
        message = " ".join(r.getMessage() for r in caplog.records)
        assert "error_type=RuntimeError" in message
        assert secret not in message
        assert "alice@example.com" not in message

    async def test_a_malformed_rewrite_also_falls_back(self) -> None:
        """The two fixes compose: no exception, but unusable output."""
        assert await rewrite_query(_FakeLLM(""), [{}], ORIGINAL) == ORIGINAL
        assert await rewrite_query(_FakeLLM(None), [{}], ORIGINAL) == ORIGINAL

    async def test_a_good_rewrite_is_returned(self) -> None:
        assert await rewrite_query(_FakeLLM("standalone?"), [{}], ORIGINAL) == (
            "standalone?"
        )

    async def test_the_prompt_messages_are_passed_through_untouched(self) -> None:
        """Plugins build their own prompts; this never constructs one."""
        llm = _FakeLLM("ok")
        messages = [{"role": "human", "content": "condense this"}]
        await rewrite_query(llm, messages, ORIGINAL)
        assert llm.calls == [messages]


class TestShouldRewriteGate:
    def test_should_rewrite_is_false_without_history(self) -> None:
        """Preserves today's precondition: nothing to resolve against."""
        assert should_rewrite(ORIGINAL, [], None) is False
        assert should_rewrite(ORIGINAL, None, _SkipNothing()) is False

    def test_a_none_policy_never_skips(self) -> None:
        """Opt-in: with no policy, behaviour matches develop."""
        assert should_rewrite(ORIGINAL, ["turn"], None) is True

    def test_a_skipping_policy_skips(self) -> None:
        assert should_rewrite(ORIGINAL, ["turn"], _SkipEverything()) is False

    def test_a_non_skipping_policy_does_not(self) -> None:
        assert should_rewrite(ORIGINAL, ["turn"], _SkipNothing()) is True

    def test_a_different_policy_governs_without_touching_this_module(self) -> None:
        """US3 — the strategy is swappable by substitution alone."""
        policy = _SkipShort()
        assert should_rewrite("yes", ["turn"], policy) is False
        assert should_rewrite(ORIGINAL, ["turn"], policy) is True

    def test_the_protocol_is_satisfied_by_any_one_method_object(self) -> None:
        for policy in (_SkipEverything(), _SkipNothing(), _SkipShort()):
            assert isinstance(policy, RewritePolicy)


class TestTheFloorProtectsShortAnaphors:
    """A pure ratio punishes exactly the queries that most need resolving.

    "who is he?" is ten characters. Resolving it yields something like "What
    are the L1 spaces in the Alkemio platform?" — a 4.7x expansion and entirely
    correct. Measured over a 14-turn anaphoric corpus, a bare ratio of 4.0
    rejected 5 legitimate resolutions and 8.0 still rejected 2.
    """

    RESOLUTION = "What are the L1 spaces in the Alkemio platform?"

    @pytest.mark.parametrize(
        "anaphor",
        ["who is he?", "why is that", "which ones", "ok?", "yes?", "and?"],
    )
    def test_a_short_anaphor_may_expand_past_the_ratio(self, anaphor: str) -> None:
        assert validate_rewrite(self.RESOLUTION, anaphor) == self.RESOLUTION

    def test_the_floor_is_not_a_blank_cheque(self) -> None:
        """A model that started explaining is still caught."""
        essay = "Well, to answer that I should first explain. " * 40
        assert len(essay) > MIN_REWRITE_ALLOWANCE
        assert validate_rewrite(essay, "who is he?") == "who is he?"

    def test_the_ratio_still_governs_a_long_original(self) -> None:
        """The floor only ever *raises* the allowance, never lowers it."""
        original = "x" * 200
        allowed = "y" * int(DEFAULT_MAX_EXPANSION_RATIO * 200)
        assert validate_rewrite(allowed, original) == allowed
        assert validate_rewrite(allowed + "y", original) == original

    def test_exactly_at_the_floor_is_accepted(self) -> None:
        at_floor = "x" * MIN_REWRITE_ALLOWANCE
        assert validate_rewrite(at_floor, "hi?") == at_floor
        assert validate_rewrite("x" * (MIN_REWRITE_ALLOWANCE + 1), "hi?") == "hi?"


class TestHistoryIsBounded:
    """The condense prompt embedded the *whole* conversation, unbounded.

    `history_length` has existed in config since before this feature and is
    read by no code at all. The member supplies the history, so the size of
    that third-party prompt was theirs to choose: 5 000 turns of 500 chars
    built a 2.5 MB prompt, sent on every request to a metered API.
    """

    def test_a_long_history_is_truncated(self) -> None:
        assert len(recent_history(list(range(5_000)))) == DEFAULT_MAX_HISTORY_TURNS

    def test_the_most_recent_turns_are_the_ones_kept(self) -> None:
        """A follow-up refers to what was just said, not to turn one."""
        assert recent_history(list(range(30)), 5) == [25, 26, 27, 28, 29]

    def test_a_short_history_is_untouched(self) -> None:
        assert recent_history([1, 2, 3]) == [1, 2, 3]

    @pytest.mark.parametrize("bad", [None, [], 12_345, object()])
    def test_a_malformed_history_yields_nothing_rather_than_raising(
        self, bad: object
    ) -> None:
        """A malformed history must not be the reason a request fails."""
        assert recent_history(bad) == []

    def test_zero_or_negative_disables_the_bound(self) -> None:
        """An operator may opt out; the default is what protects them."""
        assert recent_history([1, 2, 3], 0) == [1, 2, 3]
        assert recent_history([1, 2, 3], -1) == [1, 2, 3]


class TestValidationIsLengthNotMeaning:
    """Records the limit of a length check, so nobody assumes it is stronger.

    A short refusal or preamble passes and becomes the retrieval query. No
    length rule can separate it from a short legitimate query — that needs
    semantics, i.e. another model call, which is the cost this feature removes.
    """

    @pytest.mark.parametrize(
        "preamble",
        ["I cannot help with that.", "Sure! Here you go:", "N/A", "..."],
    )
    def test_a_short_preamble_is_not_caught(self, preamble: str) -> None:
        assert validate_rewrite(preamble, "who is he?") == preamble

    def test_a_short_legitimate_query_is_indistinguishable_by_length(self) -> None:
        """Why the above cannot simply be fixed here."""
        legit = "Who is the lead of Space Alpha?"
        assert len(legit) < MIN_REWRITE_ALLOWANCE
        assert validate_rewrite(legit, "who is he?") == legit


class TestHistoryIsBoundedByCharactersToo:
    """The turn count alone leaves the volume to the member.

    The platform caps a single room message at 32 784 chars, so 20 turns is
    still ~656 000 chars — ~164 000 tokens — re-sent to a metered API on every
    turn of a thread.
    """

    def test_the_character_budget_is_enforced(self) -> None:
        """20 turns at the platform's message cap is ~656 000 chars unbounded.

        The kept volume is one oversized turn, not twenty: at least one turn is
        always kept (see below), so the ceiling is the budget plus the single
        largest recent turn — not a multiple of the turn count.
        """
        history = [{"role": "human", "content": "x" * 32_784} for _ in range(20)]
        kept = recent_history(history)
        total = sum(len(t["content"]) for t in kept)
        assert total < 40_000, f"kept {total:,} chars"
        assert total < 0.1 * (20 * 32_784)

    def test_the_most_recent_turns_survive_the_budget(self) -> None:
        """Oldest-first eviction — a follow-up refers to what was just said."""
        history = [{"role": "human", "content": f"turn{i}" + "x" * 4_000}
                   for i in range(10)]
        kept = recent_history(history)
        assert kept[-1]["content"].startswith("turn9")
        assert len(kept) < 10

    def test_one_oversized_turn_is_still_kept(self) -> None:
        """Dropping every turn would silently defeat the resolution the prompt
        exists to perform — worse than sending a large one."""
        history = [{"role": "human", "content": "x" * 100_000}]
        assert len(recent_history(history)) == 1

    def test_a_short_history_is_untouched_by_the_budget(self) -> None:
        history = [{"role": "human", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        assert recent_history(history) == history

    def test_a_turn_without_string_content_does_not_raise(self) -> None:
        assert len(recent_history([{"role": "human"}, {"content": None}])) == 2

    def test_a_non_positive_budget_disables_the_character_bound(self) -> None:
        history = [{"role": "human", "content": "x" * 50_000} for _ in range(3)]
        assert len(recent_history(history, max_chars=0)) == 3
