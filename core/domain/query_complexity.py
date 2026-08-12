"""Pure, inspectable question-complexity classification for answering prompts.

The rule is intentionally small and deterministic: a question is complex when
any one of these signals fires:

* a comparative or analytical cue is present;
* it contains multiple distinct asks (multiple ``?`` characters or two
  interrogatives joined by ``and`` / ``or``); or
* it contains more than :data:`LONG_QUESTION_WORD_THRESHOLD` words.

These cues and the threshold are the operator-facing definition of the
feature.  This module performs no I/O and never calls a model.
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
_INTERROGATIVE_RE = re.compile(
    r"\b(?:what|why|how|which|where|when|who|can|should|does|do|is|are)\b"
    r"[^?]*\b(?:and|or)\b[^?]*"
    r"\b(?:what|why|how|which|where|when|who|can|should|does|do|is|are)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


def classify_question(text: str) -> tuple[QueryComplexity, frozenset[str]]:
    """Classify *text* using only lexical and structural signals.

    Any signal is sufficient to classify a question as complex.  The returned
    signal names make the result inspectable in tests and diagnostics.
    """

    signals: set[str] = set()
    if _CUE_RE.search(text):
        signals.add(COMPARATIVE_ANALYTICAL_SIGNAL)
    if text.count("?") > 1 or _INTERROGATIVE_RE.search(text):
        signals.add(MULTIPLE_ASKS_SIGNAL)
    if len(_WORD_RE.findall(text)) > LONG_QUESTION_WORD_THRESHOLD:
        signals.add(LENGTH_SIGNAL)

    complexity = (
        QueryComplexity.COMPLEX if signals else QueryComplexity.STRAIGHTFORWARD
    )
    return complexity, frozenset(signals)
