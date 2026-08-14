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

#: Characters of the answer examined for hedging, at each end. An answer
#: declines at its opening or in its closing caveat; scanning the whole body
#: costs real time on the response path. Measured: a 100 kB answer goes from
#: 70 ms to 1.4 ms.
#:
#: Both ends are scanned because review showed a long answer that hedges only
#: in a trailing sentence was missed by a head-only scan. The cost stays O(1):
#: two fixed windows regardless of answer size.
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
    # Apologetic and colloquial declines. Added after review measured 13/13
    # spurious flags on this class: every one is the model correctly refusing,
    # and flagging a refusal is the worst error this feature can make.
    "i don't have that",
    "i do not have that",
    "i don't have access",
    "i don't have anything",
    "i don't have an answer",
    "i don't have enough",
    "i'm afraid i can't",
    "i am afraid i can't",
    "i'm not sure about",
    "i am not sure about",
    "i'm not sure i can",
    "i'd need more",
    "i would need more",
    "not something i'm able to",
    "not something i am able to",
    "outside what i can",
    "sorry, i don't",
    "sorry, i do not",
    "unfortunately, i don't",
    "unfortunately, i do not",
)

#: Every entry above must *itself* state the lack. A bare apology or softener
#: ("i'm sorry", "i'm not sure") is not a decline — review showed it suppressed
#: "I'm sorry to hear that. The space was founded in 1997 by Dr. Amelia
#: Hartwell." An apology is the most common opener there is, so admitting one
#: as a substring hands the model a prefix that disables the check.

#: A structural decline: **the speaker** saying they lack the information.
#:
#: The first-person subject is load-bearing, not decoration. A free-floating
#: negation near an information noun matches ordinary assertions about limits —
#: "The platform does not support SAML; only OIDC records are kept" is a claim,
#: not a decline, and review measured 8 of 9 such fabrications silently
#: suppressed. Negated assertions are exactly how a model states a constraint,
#: and Alkemio's own vocabulary (knowledge/context/data/records) is the noun
#: set, so the unanchored form failed on a large and ordinary class of answers.
#:
#: Contracted negations are matched as whole words: ``\bn't\b`` cannot work,
#: because the apostrophe leaves no word boundary before the "n" inside
#: ``don't``.
_HEDGE_RE = re.compile(
    r"\b(?:i|we)\b"
    r"[^.!?]{0,30}?"
    r"\b(?:do not|don't|does not|doesn't|cannot|can't|could not|couldn't"
    r"|am not|'m not|are not|aren't|was not|wasn't|have no|has no|had no"
    r"|lack|lacks|lacking|unable|without)\b"
    r"[^.!?]{0,40}?"
    r"\b(?:information|context|knowledge|details?|data|evidence|records?|"
    r"sources?|documentation|answer|idea)\b",
    re.IGNORECASE,
)


#: Reason codes this feature emits. Anything else came from a substituted
#: validator and is not trusted into a log line.
KNOWN_REASONS = frozenset({
    "context_present", "empty_answer", "declined", "no_context", "disabled",
})


def safe_reason(reason: object) -> str:
    """Reduce a verdict reason to a known code before it is logged.

    `reason` is free text on the port, so a substituted validator could build
    it from the member's answer. Logs go to stdout and on to central logging,
    where they are readable by anyone with log access rather than by space
    membership — so only codes this module defines get through.
    """
    # `reason` is deliberately typed `object`: the point is that a substituted
    # validator may return anything at all, including a non-str carrying member
    # content. Membership in the allow-list is what makes it a str.
    return reason if isinstance(reason, str) and reason in KNOWN_REASONS else "unknown"


def is_context_empty(context: str) -> bool:
    """Whether retrieval produced nothing usable.

    Both representations count: expert's empty string and guidance's sentinel.
    """
    if not context:
        return True
    stripped = context.strip()
    # Case-folded: the sentinel is a literal in the guidance plugin today, but
    # a reworded constant differing only in case would silently turn this check
    # off for half the traffic rather than fail loudly.
    return not stripped or stripped.casefold() == NO_CONTEXT_SENTINEL.casefold()


def is_hedged(answer: str) -> bool:
    """Whether the answer declines rather than asserts.

    Curly apostrophes are normalised first — models emit them freely, and
    ``don’t`` would otherwise slip past every pattern written with ``don't``.
    """
    if not answer:
        return False
    # Head and tail. A hedge in a closing caveat is still a decline, and
    # missing it costs a spurious flag on an answer that behaved correctly.
    if len(answer) <= 2 * MAX_SCANNED_CHARS:
        window = answer
    else:
        window = f"{answer[:MAX_SCANNED_CHARS]}\n{answer[-MAX_SCANNED_CHARS:]}"
    text = window.replace("’", "'").lower()
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
