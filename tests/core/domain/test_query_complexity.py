"""Truth-table tests for the pure answering question-complexity heuristic."""

from __future__ import annotations

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
        ("これは何ですか？", QueryComplexity.STRAIGHTFORWARD, set()),
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
