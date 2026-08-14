"""Faithfulness detection — and above all, what it must never flag.

The value of this check is entirely in its precision. A flag that fires on
faithful answers is worse than no flag: it becomes noise people learn to skip.
So most of these tests assert that nothing happens.
"""

from __future__ import annotations

import time

import pytest

from core.domain.faithfulness import (
    NO_CONTEXT_SENTINEL,
    ContextSufficiencyValidator,
    NoopValidator,
    is_context_empty,
    is_hedged,
)
from core.ports.faithfulness import FaithfulnessValidatorPort

VALIDATOR = ContextSufficiencyValidator()

REAL_CONTEXT = "To invite members to a space, open Space settings and click Invite."

#: Every way the two plugins can say "retrieval found nothing".
EMPTY_SHAPES = ["", "   ", "\n\n", "\t", NO_CONTEXT_SENTINEL, f"  {NO_CONTEXT_SENTINEL}  "]

#: Ways a model declines. Flagging any of these would condemn the model for
#: doing exactly what it was told to do.
HEDGES = [
    "I don't have enough information to answer that.",
    "I don’t have enough information to answer that.",   # curly apostrophe
    "I do not have enough information.",
    "I don't know.",
    "I do not know the answer to that.",
    "There is no relevant information in the provided knowledge.",
    "No information is available on that topic.",
    "The knowledge provided doesn't contain enough information.",
    "The context doesn't contain details about that.",
    "I'm not able to find that in the available context.",
    "I could not find any details about that.",
    "I couldn't find relevant records.",
    "Unable to answer from the provided context.",
    "I cannot answer that without more information.",
    "There is insufficient information to respond.",
    "The provided context does not contain that data.",
]


class TestPortConformance:
    def test_validator_satisfies_the_port(self) -> None:
        assert isinstance(VALIDATOR, FaithfulnessValidatorPort)

    def test_noop_satisfies_the_port(self) -> None:
        assert isinstance(NoopValidator(), FaithfulnessValidatorPort)

    def test_validate_is_synchronous(self) -> None:
        """An async signature would invite a network call behind this port."""
        import inspect

        assert not inspect.iscoroutinefunction(VALIDATOR.validate)


class TestEmptyContextShapes:
    """Both plugins must be covered — they represent "nothing" differently."""

    @pytest.mark.parametrize("context", EMPTY_SHAPES)
    def test_recognised_as_empty(self, context: str) -> None:
        assert is_context_empty(context)

    @pytest.mark.parametrize(
        "context",
        [REAL_CONTEXT, "[source:0] anything at all", NO_CONTEXT_SENTINEL + " but also this"],
    )
    def test_real_context_is_not_empty(self, context: str) -> None:
        assert not is_context_empty(context)


class TestHedgeDetection:
    @pytest.mark.parametrize("answer", HEDGES)
    def test_declines_are_detected(self, answer: str) -> None:
        assert is_hedged(answer)

    @pytest.mark.parametrize(
        "answer",
        [
            # Confident answers that merely contain the vocabulary.
            "You can find that information in the Space settings panel.",
            "There are no fewer than five callouts in this space.",
            "The knowledge base contains details about the onboarding process.",
            "Data about members is shown on the community page.",
            "The mission is to accelerate collaboration.",
        ],
    )
    def test_confident_answers_are_not_hedges(self, answer: str) -> None:
        assert not is_hedged(answer)

    def test_empty_answer_is_not_a_hedge(self) -> None:
        assert not is_hedged("")


class TestTheOnlyThingItFlags:
    def test_assertive_answer_on_no_context_is_flagged(self) -> None:
        verdict = VALIDATOR.validate(
            answer="The space was founded in 1997 by Dr. Amelia Hartwell.",
            context="",
        )
        assert verdict.supported is False
        assert verdict.reason == "no_context"

    def test_the_guidance_sentinel_counts_too(self) -> None:
        verdict = VALIDATOR.validate(
            answer="The mission is to accelerate renewable energy adoption.",
            context=NO_CONTEXT_SENTINEL,
        )
        assert verdict.supported is False


class TestWhatItMustNeverFlag:
    """The precision guarantees. Each of these was a rejected design."""

    def test_a_faithful_paraphrase_is_never_flagged(self) -> None:
        """Word-overlap scoring would have flagged this. That is why it is gone."""
        verdict = VALIDATOR.validate(
            answer="You can add people to a space through the settings panel.",
            context=REAL_CONTEXT,
        )
        assert verdict.supported is True
        assert verdict.reason == "context_present"

    def test_a_non_english_answer_is_never_flagged(self) -> None:
        """The platform answers in the member's language.

        Overlap scoring gave a Dutch answer over English context the same score
        as a fabrication — it would have flagged every non-English answer on the
        platform.
        """
        verdict = VALIDATOR.validate(
            answer="Je kunt leden toevoegen via het instellingenpaneel.",
            context=REAL_CONTEXT,
        )
        assert verdict.supported is True

    @pytest.mark.parametrize("answer", HEDGES)
    def test_declining_on_no_evidence_is_correct_behaviour(self, answer: str) -> None:
        assert VALIDATOR.validate(answer=answer, context="").supported is True

    def test_an_empty_answer_asserts_nothing(self) -> None:
        assert VALIDATOR.validate(answer="", context="").supported is True
        assert VALIDATOR.validate(answer="   ", context="").supported is True

    def test_context_is_checked_before_wording(self) -> None:
        """Order is load-bearing.

        With real context present, even an answer sharing not one word with it
        is supported — which is what makes paraphrase and translation
        structurally impossible to flag rather than merely unlikely.
        """
        verdict = VALIDATOR.validate(
            answer="Zzzz qqqq wwww vvvv.", context=REAL_CONTEXT,
        )
        assert verdict.supported is True
        assert verdict.reason == "context_present"


class TestCostIsNegligible:
    def test_a_large_answer_stays_within_budget(self) -> None:
        """This runs on the response path; an unbounded scan would be felt."""
        answer = "The mission is to accelerate collaboration. " * 2_500  # ~100 kB
        start = time.perf_counter()
        for _ in range(20):
            VALIDATOR.validate(answer=answer, context="")
        per_call_ms = (time.perf_counter() - start) * 1000 / 20
        assert per_call_ms < 10, f"{per_call_ms:.2f}ms per validation"

    def test_the_common_path_is_effectively_free(self) -> None:
        """Context present is the overwhelmingly common case."""
        start = time.perf_counter()
        for _ in range(1000):
            VALIDATOR.validate(answer="an answer", context=REAL_CONTEXT)
        per_call_ms = (time.perf_counter() - start) * 1000 / 1000
        assert per_call_ms < 0.1


class TestNoopValidator:
    @pytest.mark.parametrize(
        ("answer", "context"),
        [("anything", ""), ("", ""), ("a fabrication", NO_CONTEXT_SENTINEL)],
    )
    def test_approves_everything(self, answer: str, context: str) -> None:
        assert NoopValidator().validate(answer=answer, context=context).supported


class TestNoOverlapScoringExists:
    def test_the_module_contains_no_overlap_machinery(self) -> None:
        """SC-012 — the rejected design must not creep back in.

        Word-overlap scoring cannot separate fabrication from paraphrase; a
        future "improvement" adding it would make this check unusable.
        """
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "core/domain/faithfulness.py"
        ).read_text(encoding="utf-8")

        # Executable code only. The module docstring explains at length WHY
        # overlap scoring was rejected, so a plain text search flags the
        # explanation — matching on identifiers is what makes this test about
        # behaviour rather than about prose.
        tree = ast.parse(source)
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        for token in ("overlap", "jaccard", "intersection", "similarity", "ratio"):
            assert not any(token in n.lower() for n in names), (
                f"{token} scoring reintroduced"
            )
        # Set intersection is the mechanic overlap scoring needs.
        assert " & " not in "\n".join(
            line.split("#")[0] for line in source.splitlines()
            if not line.strip().startswith(("#", '"', "'"))
        )
