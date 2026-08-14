"""Pure, inspectable question-complexity classification for answering prompts.

The rule is intentionally small and deterministic: a question is complex when
any one of these signals fires:

* a comparative or analytical cue is present;
* it contains multiple distinct asks (multiple ``?`` / ``？`` characters or two
  interrogatives joined by ``and`` / ``or``); or
* it contains more than :data:`LONG_QUESTION_WORD_THRESHOLD` words.

These cues and the threshold are the operator-facing definition of the
feature. The lexical cue and interrogative lists are English-only; the
multi-question signal also recognizes fullwidth ``？``. This module performs
no I/O and never calls a model.
"""

from __future__ import annotations

from enum import Enum
import re


class QueryComplexity(str, Enum):
    """The two answering modes selected by the complexity heuristic."""

    STRAIGHTFORWARD = "straightforward"
    COMPLEX = "complex"


COMPARATIVE_ANALYTICAL_SIGNAL = "comparative_or_analytical"
MULTIPLE_ASKS_SIGNAL = "multiple_asks"
LENGTH_SIGNAL = "length"

# More than 24 words is long enough that a direct, single-pass response often
# misses a qualification.  Operators can predict the rule from this constant.
LONG_QUESTION_WORD_THRESHOLD = 24

_CUE_PATTERNS = (
    r"\bcompare(?:d|s|ing)?\b",
    r"\bversus\b",
    r"\bvs\.?\b",
    r"\bdiffer(?:s|ed|ent|ence)?\b",
    r"\bdifference(?:s)?\b",
    r"\btrade[ -]?offs?\b",
    r"\bpros?\s+and\s+cons?\b",
    r"\banaly[sz](?:e|es|ed|ing)?\b",
    r"\bevaluat(?:e|es|ed|ing|ion)\b",
    r"\bwhy\b",
    r"\bwhich\s+(?:is|are)\s+(?:better|best)\b",
)
_CUE_RE = re.compile("|".join(_CUE_PATTERNS), re.IGNORECASE)
_INTERROGATIVE_TOKENS = frozenset(
    {
        "what",
        "why",
        "how",
        "which",
        "where",
        "when",
        "who",
        "can",
        "should",
        "does",
        "do",
        "is",
        "are",
    }
)
_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)
_CLASSIFICATION_TEXT_LIMIT = 2000


def _has_conjoined_interrogatives(tokens: list[str]) -> bool:
    """Return whether two interrogatives have ``and`` or ``or`` between them."""

    seen_interrogative = False
    seen_conjunction = False
    for token in tokens:
        normalized = token.casefold()
        if normalized in _INTERROGATIVE_TOKENS:
            if seen_conjunction:
                return True
            seen_interrogative = True
        elif normalized in {"and", "or"} and seen_interrogative:
            seen_conjunction = True
    return False


def classify_question(text: str) -> tuple[QueryComplexity, frozenset[str]]:
    """Classify *text* using only lexical and structural signals.

    Any signal is sufficient to classify a question as complex.  The returned
    signal names make the result inspectable in tests and diagnostics.
    """

    bounded_text = text[:_CLASSIFICATION_TEXT_LIMIT]
    tokens = _WORD_RE.findall(bounded_text)

    signals: set[str] = set()
    if _CUE_RE.search(bounded_text):
        signals.add(COMPARATIVE_ANALYTICAL_SIGNAL)
    if (
        bounded_text.count("?") + bounded_text.count("？") > 1
        or _has_conjoined_interrogatives(tokens)
    ):
        signals.add(MULTIPLE_ASKS_SIGNAL)
    if len(tokens) > LONG_QUESTION_WORD_THRESHOLD:
        signals.add(LENGTH_SIGNAL)

    complexity = (
        QueryComplexity.COMPLEX if signals else QueryComplexity.STRAIGHTFORWARD
    )
    return complexity, frozenset(signals)
