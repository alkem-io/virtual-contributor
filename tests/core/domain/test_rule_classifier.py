"""Query classification, and the one property that actually matters.

Accuracy is secondary here. The load-bearing assertion is that **no genuine
question is ever routed to skip retrieval** — every other mistake costs a
little latency or reproduces today's behaviour, but that one answers a member
ungrounded.
"""

from __future__ import annotations

import pytest

from core.domain.rule_classifier import RuleQueryClassifier
from core.ports.query_router import QueryRouterPort, RouteClass

CLASSIFIER = RuleQueryClassifier()


def _route(message: str) -> RouteClass:
    return CLASSIFIER.classify(message).route


#: Real questions. None of these may ever skip retrieval, whatever else the
#: classifier decides about them.
GENUINE_QUESTIONS = [
    # The regression that motivated anchoring: "hi" appears inside "which".
    "Which subspaces exist here?",
    # Opens with thanks, then asks something.
    "Thanks - can you also tell me who the space lead is?",
    "ok so what is the mission of this space",
    "sure, but how do I invite members?",
    "yes and where do I find the callouts",
    "What is the mission of this space?",
    "Who is the lead of this space?",
    "How do I invite members to a space?",
    "Why was this challenge created?",
    "Compare the goals of subspace A and subspace B",
    "What is the difference between a space and a subspace?",
    "Explain how callouts work",
    "tell me about the whiteboard feature",
    "could you please just tell me what the name of the lead of this space is",
    "no idea how this works, can you explain?",
    "hi, what is the mission?",
    "cheers, and what about the roadmap",
]

#: Small talk. Nothing in a knowledge base answers these.
SMALL_TALK = [
    "hi", "Hi there", "hello", "Hey!", "good morning", "Good afternoon",
    "thanks", "Thanks!", "thank you", "Thank you so much", "thx", "cheers",
    "got it", "Got it, thanks", "understood", "makes sense", "noted",
    "ok", "okay", "Alright", "sure", "cool", "nice", "great", "perfect",
    "bye", "goodbye", "see you", "take care",
    "yes", "no", "yep", "nope",
    "sorry", "my bad", "no worries",
]


class TestPortConformance:
    def test_classifier_satisfies_the_port(self) -> None:
        assert isinstance(CLASSIFIER, QueryRouterPort)

    def test_decision_carries_a_reason(self) -> None:
        """Without it, a misrouted question looks like a badly-answered one."""
        assert CLASSIFIER.classify("hi").reason
        assert CLASSIFIER.classify("what is the mission?").reason


class TestSafetyAsymmetry:
    """The core guarantee — SC-007, SC-008."""

    @pytest.mark.parametrize("message", GENUINE_QUESTIONS)
    def test_no_genuine_question_ever_skips_retrieval(self, message: str) -> None:
        assert _route(message) is not RouteClass.CONVERSATIONAL

    @pytest.mark.parametrize(
        "message",
        [
            "thanks?",                    # a question mark makes it a question
            "ok?",
            "hi?",
            "Bedankt!",                   # not English — must not be guessed at
            "Merci beaucoup",
            "Danke schön",
            "",                           # nothing to classify
            "   ",
            "\n\t ",
        ],
    )
    def test_ambiguous_input_falls_back_to_retrieval(self, message: str) -> None:
        assert _route(message) is not RouteClass.CONVERSATIONAL

    def test_a_question_mark_alone_disqualifies_small_talk(self) -> None:
        assert _route("thanks") is RouteClass.CONVERSATIONAL
        assert _route("thanks?") is not RouteClass.CONVERSATIONAL


class TestRoutes:
    @pytest.mark.parametrize("message", SMALL_TALK)
    def test_small_talk_skips_retrieval(self, message: str) -> None:
        assert _route(message) is RouteClass.CONVERSATIONAL

    @pytest.mark.parametrize(
        "message",
        [
            "Compare the goals of subspace A and subspace B",
            "What is the difference between a space and a subspace?",
            "How does A relate to B?",
            "spaces versus subspaces",
            "what are the trade-offs here",
            "how should we prioritise these challenges",
            "pros and cons of this approach",
        ],
    )
    def test_comparative_questions_route_complex(self, message: str) -> None:
        assert _route(message) is RouteClass.COMPLEX

    @pytest.mark.parametrize(
        "message",
        [
            "How do I invite members?",
            "Why was this space created?",
            "Explain how callouts work",
            "Describe the onboarding process",
            "tell me about the roadmap",
        ],
    )
    def test_explanatory_questions_route_moderate(self, message: str) -> None:
        assert _route(message) is RouteClass.MODERATE

    @pytest.mark.parametrize(
        "message",
        [
            "What is the mission of this space?",
            "Who is the space lead?",
            "When was this created?",
            "the name of the lead",
        ],
    )
    def test_direct_lookups_route_simple(self, message: str) -> None:
        assert _route(message) is RouteClass.SIMPLE


class TestNoLengthRule:
    """Length was ablated out — it contributed zero accuracy and misrouted.

    Pinned because reintroducing "long message means complex" looks like an
    obvious improvement and is not: length tracks how elaborately someone
    writes, not how hard the question is.
    """

    def test_a_verbose_simple_lookup_stays_simple(self) -> None:
        message = (
            "could you please just tell me what the name of the lead "
            "of this particular space happens to be"
        )
        assert len(message.split()) > 15
        assert _route(message) is RouteClass.SIMPLE

    def test_a_terse_comparison_is_still_complex(self) -> None:
        assert len("A vs B".split()) < 4
        assert _route("A vs B") is RouteClass.COMPLEX


class TestDeterminism:
    @pytest.mark.parametrize(
        "message", ["hi", "what is the mission?", "compare A and B", ""],
    )
    def test_same_input_same_route(self, message: str) -> None:
        first = CLASSIFIER.classify(message)
        assert all(CLASSIFIER.classify(message) == first for _ in range(20))

    def test_classification_never_raises(self) -> None:
        for message in ["", "   ", "?" * 500, "\x00\x01", "🙂", "a" * 10_000]:
            assert CLASSIFIER.classify(message).route in RouteClass


class TestAdversarialSmallTalkPrefixes:
    """Questions engineered to look like small talk must still retrieve.

    The dangerous shape is a message that *opens* with an acknowledgement and
    then asks something. Anchoring the whole message is what separates these
    from real small talk; a prefix or substring match would skip retrieval on
    every one of them.
    """

    @pytest.mark.parametrize(
        "message",
        [
            "ok so", "ok so what", "ok so what now",
            "thanks for the space overview",
            "hi can you help",
            "yes the mission",
            "no the other one",
            "sure thing tell me more",
            "great what next",
            "cool where is it",
            "right so who leads",
            "got it and the roadmap",
            "perfect now the callouts",
            "nice and the members",
            "hello world",
            "thanks a lot for everything you have done",
        ],
    )
    def test_acknowledgement_followed_by_content_still_retrieves(
        self, message: str,
    ) -> None:
        assert _route(message) is not RouteClass.CONVERSATIONAL

    @pytest.mark.parametrize("message", ["ok", "yes.", "no!", "cheers mate"])
    def test_bare_acknowledgements_do_skip_retrieval(self, message: str) -> None:
        """The other half of the property: it must not be uselessly strict."""
        assert _route(message) is RouteClass.CONVERSATIONAL
