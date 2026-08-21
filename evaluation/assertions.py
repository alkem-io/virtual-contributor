"""Deterministic exact-match assertion layer.

Derives literal, checkable facts from an ``expected_answer`` by rule, and
evaluates them against a pipeline's answer by pure string comparison. This
module must never import a model client, open a socket, or read credentials
— see FR-014. It is a complement to the RAGAS judged metrics, not a
replacement: only a minority of cases carry a checkable literal fact (see
``forge/measured-anchors.md`` in the workspace spec), so most cases are
judge-only by design.

The derivation rule is deliberately conservative. An earlier, broader
enumeration pattern raised coverage but manufactured assertions out of prose
fragments ("a non-linear", "while embracing ambiguity") — fluency-matching
wearing a deterministic mask. This module trades coverage for honesty: it
only fires on facts that are genuinely literal (a quoted UI label, an email
address, a bare domain, a licence identifier) or on an answer that is
entirely a short enumeration of concrete items.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

AssertionKind = Literal["contains", "contains_all"]


class Assertion(BaseModel):
    """One derived, checkable fact about an expected answer."""

    kind: AssertionKind
    values: list[str] = Field(min_length=1)


class AssertionOutcome(BaseModel):
    """The result of evaluating a case's assertions against a pipeline answer."""

    status: Literal["passed", "failed", "not_applicable"]
    missing: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """NFC + casefold + whitespace collapse (FR-015, C-3).

    NFC only — never NFKC, which rewrites U+2122 (TM) to the ASCII digraph
    "TM" and would silently alter operator wording under comparison.
    """
    nfc = unicodedata.normalize("NFC", text)
    return " ".join(nfc.casefold().split())


# ---------------------------------------------------------------------------
# Derivation — literal patterns (-> contains)
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DOMAIN_RE = re.compile(r"\b((?:[A-Za-z0-9-]+\.)+([A-Za-z]{2,}))\b")
_DOMAIN_TLDS = {"com", "org", "net", "io", "edu", "gov", "co"}
_QUOTE_RE = re.compile(r'"([^"]{2,60})"')
_LICENCE_RE = re.compile(r"\b(EUPL|MIT|Apache|GPL|AGPL|LGPL|BSD)(?:[- ]v?\d+(?:\.\d+)?)?\b")


def _mask_emails(text: str) -> str:
    """Blank out email addresses before domain matching.

    Without this, the domain pattern would re-match ``alkem.io`` out of
    ``support@alkem.io`` as a second, redundant anchor.
    """
    return _EMAIL_RE.sub(" ", text)


def _literal_values(answer: str) -> list[str]:
    """Extract literal quotable facts: email, bare domain, quoted phrase, licence."""
    values: list[str] = []
    for match in _EMAIL_RE.finditer(answer):
        values.append(match.group(0))
    masked = _mask_emails(answer)
    for match in _DOMAIN_RE.finditer(masked):
        if match.group(2).lower() in _DOMAIN_TLDS:
            values.append(match.group(1))
    for match in _QUOTE_RE.finditer(answer):
        values.append(match.group(1))
    for match in _LICENCE_RE.finditer(answer):
        values.append(match.group(0))

    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


# ---------------------------------------------------------------------------
# Derivation — whole-answer enumeration (-> contains_all)
# ---------------------------------------------------------------------------

_LEADING_CONJUNCTION_RE = re.compile(r"^(and|or)\s+(.*)$", re.IGNORECASE)
_STOPWORDS = {
    "while", "through", "by", "to", "that", "where", "which",
    "not", "being", "or", "and", "yes", "no",
}


def _split_top_level_commas(text: str) -> list[str]:
    """Split on commas outside parentheses so a parenthetical stays one item."""
    items: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char == "(":
            depth += 1
            current += char
        elif char == ")":
            depth -= 1
            current += char
        elif char == "," and depth == 0:
            items.append(current)
            current = ""
        else:
            current += char
    items.append(current)
    return [item.strip() for item in items]


def _enumeration_values(answer: str) -> list[str] | None:
    """Detect an answer that is entirely a short list of concrete items.

    Fires only when: the answer ends in a period; splitting on top-level
    commas yields at least three items; every item is at most four words
    with balanced parentheses; and the first item does not open with a
    stop-word (which would signal a sentence fragment, not a list).
    """
    stripped = answer.strip()
    if not stripped.endswith("."):
        return None
    body = stripped[:-1]
    items = _split_top_level_commas(body)
    if len(items) < 3:
        return None

    conjunction_match = _LEADING_CONJUNCTION_RE.match(items[-1])
    if conjunction_match:
        items[-1] = conjunction_match.group(2)

    cleaned = [item.strip() for item in items if item.strip()]
    if len(cleaned) < 3:
        return None

    for item in cleaned:
        if item.count("(") != item.count(")"):
            return None
        word_count = len(item.split())
        if word_count == 0 or word_count > 4:
            return None

    first_token = re.split(r"\s+", cleaned[0])[0].lower().strip("()")
    if first_token in _STOPWORDS:
        return None

    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_assertions(expected_answer: str) -> list[Assertion]:
    """Mechanically derive assertions from an expected answer (FR-011, FR-012).

    Never hand-annotated: the same rule applied to the same text always
    produces the same output, and re-running it after an operator edits an
    answer re-derives correctly with no manual step (FR-012a/FR-012b).
    """
    assertions: list[Assertion] = []

    literal_values = _literal_values(expected_answer)
    if literal_values:
        assertions.append(Assertion(kind="contains", values=literal_values))

    enumeration_values = _enumeration_values(expected_answer)
    if enumeration_values:
        assertions.append(Assertion(kind="contains_all", values=enumeration_values))

    return assertions


def evaluate_assertions(answer: str, assertions: list[Assertion]) -> AssertionOutcome:
    """Evaluate assertions against a pipeline answer by literal substring match.

    No model client, no socket, no credentials (FR-014) — this is pure string
    comparison after NFC normalization, case-folding, and whitespace collapse.
    Returns ``not_applicable`` when there is nothing to check (FR-016), so a
    case with no derived facts is never silently counted as passing.
    """
    if not assertions:
        return AssertionOutcome(status="not_applicable")

    normalized_answer = _normalize(answer)
    missing: list[str] = []
    for assertion in assertions:
        for value in assertion.values:
            if _normalize(value) not in normalized_answer:
                missing.append(value)

    if missing:
        return AssertionOutcome(status="failed", missing=missing)
    return AssertionOutcome(status="passed")
