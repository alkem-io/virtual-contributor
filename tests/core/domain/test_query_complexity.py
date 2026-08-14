"""Truth-table tests for the pure answering question-complexity heuristic."""

from __future__ import annotations

import pytest

from core.domain.query_complexity import (
    COMPARATIVE_ANALYTICAL_SIGNAL,
    LENGTH_SIGNAL,
    MULTIPLE_ASKS_SIGNAL,
    _WORD_RE,
    _has_conjoined_interrogatives,
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

    complexity, signals = classify_question(question)

    assert complexity is QueryComplexity.COMPLEX
    assert signals == {LENGTH_SIGNAL}


def test_interrogative_detection_does_no_regex_backtracking() -> None:
    """Pin the *structural* property SEC-1 fixed, not its wall-clock shadow.

    The pre-fix detector was a single regex with two unbounded ``[^?]*``
    spans between alternation groups — the shape that backtracks
    catastrophically. A wall-clock assertion cannot stand in for this:
    with the 2000-char bound also in place the vulnerable regex completes
    in ~17 ms, so any threshold loose enough to survive a loaded CI runner
    is also loose enough to admit the vulnerability it claims to exclude.

    Assert the invariant directly instead: interrogative detection is a
    linear token scan, and no module-level pattern contains an unbounded
    quantifier adjacent to an alternation group.
    """
    import re as _re

    from core.domain import query_complexity as qc

    # The detector is a pure token-list scan, not a regex match.
    assert not any(
        isinstance(getattr(qc, name), _re.Pattern)
        and "and|or" in getattr(qc, name).pattern
        for name in dir(qc)
    )
    assert isinstance(qc._INTERROGATIVE_TOKENS, frozenset)

    # No compiled pattern in the module nests a quantifier over a group
    # that can also match via an adjacent alternation (the ReDoS shape).
    for name in dir(qc):
        pattern = getattr(qc, name)
        if isinstance(pattern, _re.Pattern):
            assert "[^?]*" not in pattern.pattern, name


def test_interrogative_scan_cost_is_linear_in_token_count() -> None:
    """Doubling the input at most ~doubles the work — no super-linear blowup.

    Counts interpreter steps via ``sys.settrace`` rather than wall time, so
    the result is independent of runner load.
    """
    import sys

    def count_steps(text: str) -> int:
        steps = 0

        def tracer(_frame, _event, _arg):
            nonlocal steps
            steps += 1
            return tracer

        sys.settrace(tracer)
        try:
            _has_conjoined_interrogatives(_WORD_RE.findall(text))
        finally:
            sys.settrace(None)
        return steps

    small = count_steps("what " + "and x " * 400)
    large = count_steps("what " + "and x " * 800)

    # Linear would be ~2x; allow generous slack but reject quadratic (~4x).
    assert large < small * 3, f"{small} -> {large} steps looks super-linear"
