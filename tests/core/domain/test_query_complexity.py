"""Truth-table tests for the pure answering question-complexity heuristic."""

from __future__ import annotations

from time import perf_counter

import pytest

from core.domain.query_complexity import (
    COMPARATIVE_ANALYTICAL_SIGNAL,
    LENGTH_SIGNAL,
    MULTIPLE_ASKS_SIGNAL,
    QueryComplexity,
    classify_question,
)


@pytest.mark.parametrize(
    ("question", "expected_complexity", "expected_signals"),
    [
        (
            "How do X and Y differ?",
            QueryComplexity.COMPLEX,
            {COMPARATIVE_ANALYTICAL_SIGNAL},
        ),
        (
            "Why does the policy apply?",
            QueryComplexity.COMPLEX,
            {COMPARATIVE_ANALYTICAL_SIGNAL},
        ),
        (
            "What is X? How does it work?",
            QueryComplexity.COMPLEX,
            {MULTIPLE_ASKS_SIGNAL},
        ),
        (
            "What is X and how do I use it?",
            QueryComplexity.COMPLEX,
            {MULTIPLE_ASKS_SIGNAL},
        ),
        (
            " ".join(["detail"] * 25),
            QueryComplexity.COMPLEX,
            {LENGTH_SIGNAL},
        ),
        (
            "Why does X affect Y?",
            QueryComplexity.COMPLEX,
            {COMPARATIVE_ANALYTICAL_SIGNAL},
        ),
        ("What is the deadline?", QueryComplexity.STRAIGHTFORWARD, set()),
        ("", QueryComplexity.STRAIGHTFORWARD, set()),
        # The lexical cue and interrogative lists are intentionally English-only.
        ("これは何ですか？", QueryComplexity.STRAIGHTFORWARD, set()),
        (
            "これは何ですか？次は何ですか？",
            QueryComplexity.COMPLEX,
            {MULTIPLE_ASKS_SIGNAL},
        ),
    ],
)
def test_classify_question_truth_table(
    question: str,
    expected_complexity: QueryComplexity,
    expected_signals: set[str],
) -> None:
    complexity, signals = classify_question(question)

    assert complexity is expected_complexity
    assert signals == expected_signals


def test_classification_is_bounded_to_the_first_2000_characters() -> None:
    complexity, signals = classify_question("x" * 2000 + " compare?")

    assert complexity is QueryComplexity.STRAIGHTFORWARD
    assert signals == frozenset()


def test_pathological_conjoined_interrogatives_are_linear_and_bounded() -> None:
    question = "what " + "and x " * 3200

    started = perf_counter()
    complexity, signals = classify_question(question)
    elapsed = perf_counter() - started

    assert elapsed < 0.05
    assert complexity is QueryComplexity.COMPLEX
    assert signals == {LENGTH_SIGNAL}
