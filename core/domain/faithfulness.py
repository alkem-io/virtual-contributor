"""Detect the one unfaithful answer that can be recognised for free.

There is exactly one case where an answer is *provably* unsupportable without a
model, without citations, and without latency: retrieval returned **nothing**
and the model answered anyway. There was no evidence, so whatever it said came
from somewhere else.

**What this deliberately does not do.** The obvious alternative — check whether
the answer's words appear in the context — was built, measured against
realistic pairs, and rejected. There is no threshold that separates a
fabrication from a faithful paraphrase, and worse, it flags the model doing
exactly the right thing:

    faithful paraphrase                 overlap 0.22–0.56
    "I don't have enough information"   overlap 0.00   <- correct behaviour
    fabrication                         overlap 0.00

Any cutoff that catches the fabrication also condemns the honest refusal. And
because the platform answers in the member's language, a Dutch answer over
English context scores 0.00 too — identical to a lie. A check that fires on
good answers is worse than no check: it trains people to ignore it.

So this measures *context sufficiency*, not content matching. Paraphrase and
non-English answers are structurally incapable of being flagged, because the
first thing checked is whether there was any context at all.
"""

from __future__ import annotations

import re

from core.ports.faithfulness import FaithfulnessVerdict

#: Guidance substitutes this when nothing survived retrieval. Expert yields an
#: empty string from ``"\n".join([])``. **Both shapes are required** — handling
#: one silently does nothing for half the traffic.
NO_CONTEXT_SENTINEL = "No relevant context found."

#: Characters of the answer examined for hedging. An answer opens by declining
#: or it does not; scanning further finds nothing and costs real time on the
#: response path. Measured: a 100 kB answer goes from 70 ms to 1.4 ms.
MAX_SCANNED_CHARS = 2_000

#: Ways of saying "I cannot answer this from what I was given". A model doing
#: this on empty context is behaving correctly and must never be flagged.
_HEDGE_PHRASES = (
    "i don't have enough information",
    "i do not have enough information",
    "i don't have sufficient information",
    "i don't have any information",
    "i don't know",
    "i do not know",
    "no relevant information",
    "no information is available",
    "not enough information",
    "insufficient information",
    "unable to answer",
    "cannot answer",
    "can't answer",
    "the knowledge provided doesn't contain",
    "the knowledge doesn't contain",
    "the context doesn't contain",
    "the provided context does not contain",
    "doesn't contain enough information",
    "does not contain enough information",
    "i'm not able to find",
    "i could not find",
    "i couldn't find",
    "no details are available",
)

#: A bounded negation near an information noun, for phrasings the list misses.
#: The two mechanisms are a union on purpose: measured during design, the list
#: alone missed 3 of 13 realistic phrasings and the regex alone missed
#: "I don't know" — ``\bn't\b`` cannot match inside ``don't``.
_HEDGE_RE = re.compile(
    r"\b(?:no|not|n't|cannot|can't|unable|lack(?:s|ing)?|without)\b"
    r"[^.!?]{0,60}?"
    r"\b(?:information|context|knowledge|details?|data|evidence|records?|"
    r"sources?|documentation)\b",
    re.IGNORECASE,
)


def is_context_empty(context: str) -> bool:
    """Whether retrieval produced nothing usable.

    Both representations count: expert's empty string and guidance's sentinel.
    """
    if not context:
        return True
    stripped = context.strip()
    return not stripped or stripped == NO_CONTEXT_SENTINEL


def is_hedged(answer: str) -> bool:
    """Whether the answer declines rather than asserts.

    Curly apostrophes are normalised first — models emit them freely, and
    ``don’t`` would otherwise slip past every pattern written with ``don't``.
    """
    if not answer:
        return False
    text = answer[:MAX_SCANNED_CHARS].replace("’", "'").lower()
    if any(phrase in text for phrase in _HEDGE_PHRASES):
        return True
    return bool(_HEDGE_RE.search(text))


class ContextSufficiencyValidator:
    """Flags an assertive answer built on no retrieved context at all."""

    def validate(self, *, answer: str, context: str) -> FaithfulnessVerdict:
        """Judge one answer.

        The order is load-bearing:

        1. **Context present → supported.** Checked first, so an answer built
           on real evidence exits here regardless of its wording. This is what
           makes paraphrase and non-English answers structurally impossible to
           flag, rather than merely unlikely to be.
        2. Empty answer → supported. Nothing was asserted.
        3. Hedged answer → supported. Declining on no evidence is correct.
        4. Otherwise → not supported.

        Step 3 can only ever *suppress* a flag, never raise one, so a gap in
        hedge detection costs at most one spurious internal log line — never a
        wrongly-approved answer.
        """
        if not is_context_empty(context):
            return FaithfulnessVerdict(
                supported=True,
                reason="context_present",
                detail="answer was generated from retrieved context",
            )
        if not answer or not answer.strip():
            return FaithfulnessVerdict(
                supported=True,
                reason="empty_answer",
                detail="no claim was made",
            )
        if is_hedged(answer):
            return FaithfulnessVerdict(
                supported=True,
                reason="declined",
                detail="answer declined to assert without evidence",
            )
        return FaithfulnessVerdict(
            supported=False,
            reason="no_context",
            detail=(
                "answer asserts content but retrieval returned no context; "
                "nothing supports it"
            ),
        )


class NoopValidator:
    """Approves everything. The pass-through when validation is disabled."""

    def validate(self, *, answer: str, context: str) -> FaithfulnessVerdict:
        return FaithfulnessVerdict(
            supported=True, reason="disabled", detail="validation disabled",
        )
