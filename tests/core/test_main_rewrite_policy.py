"""The policy adapter in `main.py` — the only code that builds a real policy.

Reviewed mutation testing showed three independent mutations of this file left
the entire suite green: inverting the fail-open handler, removing the
`try/except` altogether, and ignoring the enable flag. Every one is a live
production behaviour, so each is pinned here.
"""

from __future__ import annotations

import logging

import pytest

import main


class _Boom:
    def classify(self, message: str):
        raise RuntimeError("classifier died")


class _Route:
    CONVERSATIONAL = object()
    SIMPLE = object()


class _Decision:
    def __init__(self, route: object) -> None:
        self.route = route


class _Classifier:
    """Routes gratitude to CONVERSATIONAL, everything else to SIMPLE.

    Normalises the same way the real classifier does — case-folded and free of
    trailing punctuation — so this stub cannot pass a message the shipped
    classifier would route differently.
    """

    _GRATITUDE = {"thanks", "thank you", "cheers", "bye", "goodbye"}

    def classify(self, message: str) -> _Decision:
        normalised = main._ConversationalSkipPolicy._normalise(message)
        return _Decision(
            _Route.CONVERSATIONAL
            if normalised in self._GRATITUDE
            else _Route.SIMPLE
        )


def _policy() -> main._ConversationalSkipPolicy:
    return main._ConversationalSkipPolicy(_Classifier(), _Route.CONVERSATIONAL)


class TestTheAdapterFailsOpen:
    """Fail-open is the safe direction and must stay that way.

    A skipped rewrite is a silent retrieval regression — an unresolved anaphor
    reaches the vector store with no error. A performed one costs only a call.
    """

    def test_a_raising_classifier_does_not_skip(self) -> None:
        policy = main._ConversationalSkipPolicy(_Boom(), _Route.CONVERSATIONAL)
        assert policy.should_skip_rewrite("thanks!") is False

    def test_a_raising_classifier_does_not_propagate(self) -> None:
        """The gate is an optimisation; it must not break what it optimises."""
        policy = main._ConversationalSkipPolicy(_Boom(), _Route.CONVERSATIONAL)
        policy.should_skip_rewrite("anything")  # must not raise

    def test_the_failure_is_logged_without_the_message(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exception body can quote the prompt, which carries conversation."""
        policy = main._ConversationalSkipPolicy(_Boom(), _Route.CONVERSATIONAL)
        with caplog.at_level(logging.WARNING, logger="main"):
            policy.should_skip_rewrite("members: alice@example.com asked about pay")
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "error_type=RuntimeError" in text
        assert "alice@example.com" not in text


class TestOnlyTerminalSmallTalkSkips:
    @pytest.mark.parametrize(
        "message",
        ["thanks", "thanks!", "thank you", "cheers", "bye", "goodbye",
         "thanks,", "cheers\u2026", "Thank you."],
    )
    def test_gratitude_and_closings_skip(self, message: str) -> None:
        assert _policy().should_skip_rewrite(message) is True

    @pytest.mark.parametrize(
        "message",
        ["ok", "okay", "alright", "will do", "later", "got it", "yep", "cool",
         "OK!", "  Okay. ", "ok,", "ok\u2026", "ok.", "Alright!!", "cool..."],
    )
    def test_an_acknowledgement_never_skips(self, message: str) -> None:
        """After "Shall I list the subspaces?", "ok" means *do it*.

        The classifier already excludes bare "yes"/"no"/"sure" on exactly this
        reasoning; it just does not extend it to these, so the gate does.
        """
        assert _policy().should_skip_rewrite(message) is False

    @pytest.mark.parametrize(
        "message", ["show me those", "the name of the lead", "and after that?"]
    )
    def test_a_non_conversational_route_never_skips(self, message: str) -> None:
        assert _policy().should_skip_rewrite(message) is False


class TestBuildingThePolicy:
    def test_returns_none_when_the_classifier_is_absent(self) -> None:
        """This base has no classifier — it ships on a separate PR. Returning
        None disables only the skip: every turn is rewritten, as on develop."""
        assert main._build_rewrite_policy() is None

    def test_the_absence_is_logged_rather_than_silent(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An operator who enables gating and gets none must be able to see why."""
        with caplog.at_level(logging.INFO, logger="main"):
            main._build_rewrite_policy()
        assert any("classifier" in r.getMessage() for r in caplog.records)


class TestTheEnableFlagIsHonoured:
    """Mutation testing showed deleting the flag check from the injection block
    left every test green, so gating would have turned on for everyone."""

    def test_the_injection_block_reads_the_flag(self) -> None:
        import inspect

        source = inspect.getsource(main)
        marker = 'if "rewrite_policy" in sig.parameters'
        assert marker in source
        line = next(ln for ln in source.splitlines() if marker in ln)
        assert "query_rewrite_gating_enabled" in line, (
            "the policy is injected without consulting the enable flag"
        )
