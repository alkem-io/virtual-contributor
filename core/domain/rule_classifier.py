"""Decide how much retrieval a question deserves, by looking at its wording.

Rules rather than a model, for one reason that decides it: a classifier that
calls an LLM costs a network round trip on **every** question, including all
the simple ones it exists to make faster. It only pays for itself if a large
share of traffic is cheap to serve *and* the cheap path saves more than one
round trip — a 350ms classifier needs 39% of all queries to hit the cheap path
just to break even. Nobody has measured that share for Alkemio. Rules cost
microseconds, so any share at all is a win, whatever it turns out to be.

**The rules are deliberately lopsided.** The four ways to be wrong are not
equally bad:

| Mistake | Consequence |
|---|---|
| real question → skip retrieval | answers ungrounded — user-visible harm |
| simple → moderate/complex | slightly slower, more context than needed |
| complex → simple | exactly today's behaviour |
| unrecognised → simple | exactly today's behaviour |

Only the first is actually harmful, so the rule that can cause it is the
strictest: skipping retrieval requires the *whole message* to match an
allow-list of small talk, with no question mark and at most six words.
Everything else falls through to a retrieving route. Every misclassification
therefore degrades to "retrieve anyway".

Pure and synchronous: no I/O, no clock, no configuration. What comes out is a
function of what goes in.
"""

from __future__ import annotations

import re

from core.ports.query_router import RouteClass, RoutingDecision, QueryRouterPort

#: Longest message that can be small talk. Anything wordier is doing more than
#: acknowledging, even if it opens with a greeting.
MAX_CONVERSATIONAL_WORDS = 6

#: Characters actually examined. Classification is synchronous and runs on the
#: event loop, so an oversized message would block every other message in the
#: process while being scanned — measured at 437ms for a 10MB query, against a
#: pod limited to ~1.5 CPU. Nothing a person types approaches this, and the
#: routes that matter are decided by the opening words in any case: a message
#: longer than this is not small talk, and truncating it cannot make it so.
MAX_CLASSIFIED_CHARS = 4_096

#: Whole-message small talk. **Anchored on purpose** — an earlier substring
#: form routed "Which subspaces exist here?" to skip retrieval, because "hi"
#: appears inside "which". Matching the entire message is what makes that
#: class of error impossible rather than unlikely.
#:
#: Bare affirmatives and negatives are deliberately **absent**: "yes", "no",
#: "sure", "please", "right", "maybe". Unlike "thanks", none of those asserts
#: that the member wants nothing looked up — after "Shall I list the templates
#: in this space?", "yes" is the shortest possible way to say *do it*.
#: Excluding them costs nothing, because they fall through to the retrieving
#: route, which is exactly today's behaviour.
_CONVERSATIONAL_RE = re.compile(
    r"^\s*(?:"
    r"(?:hi|hey|hello|yo|greetings)"
    r"|(?:good\s+(?:morning|afternoon|evening|day))"
    r"|(?:thanks?|thank\s+you|thx|ty|cheers|much\s+appreciated)"
    r"|(?:ok|okay|alright|cool|nice|great|awesome|perfect|excellent)"
    r"|(?:got\s+it|understood|makes\s+sense|noted|fair\s+enough|will\s+do)"
    r"|(?:bye|goodbye|see\s+you|later|farewell|take\s+care)"
    r"|(?:sorry|my\s+bad|no\s+worries|np)"
    r"|(?:how\s+are\s+you|how's\s+it\s+going|what's\s+up|sup)"
    r")"
    r"(?:[\s,!.\-–—]+(?:"
    r"there|all|everyone|again|so\s+much|a\s+lot|very\s+much|mate|friend|team"
    r"|that\s+(?:was\s+)?(?:helpful|great|useful|perfect)"
    r"|for\s+(?:that|the\s+help|your\s+help)"
    r"|and\s+(?:thanks?|bye|goodbye)"
    r"|cheers|thanks?|bye|goodbye|ok|okay"
    r"))*"
    r"[\s,!.…\-–—]*$",
    re.IGNORECASE,
)

#: Comparative and multi-hop markers. Word-boundary anchored so "compared"
#: matches but "incomparable" does not.
_COMPLEX_RE = re.compile(
    r"\b(?:"
    r"compare[ds]?|comparison|contrast(?:ed|ing)?"
    r"|difference[s]?\s+between|differ(?:s|ence)?\s+from"
    r"|versus|vs\.?"
    r"|relate[sd]?\s+to|relationship\s+between|connection\s+between"
    r"|both\s+\w+\s+and|between\s+\w+\s+and"
    r"|trade-?offs?|pros\s+and\s+cons"
    r"|prioriti[sz]e[sd]?|rank(?:ing)?\s+\w+\s+against"
    r"|which\s+of\s+(?:these|them|the)"
    r"|across\s+(?:all|multiple|several|both)"
    r"|impact\s+of\s+\w+\s+on"
    r")\b",
    re.IGNORECASE,
)

#: Explanatory openers — questions wanting reasoning rather than a fact.
_MODERATE_RE = re.compile(
    r"^\s*(?:"
    r"how\b|why\b|explain\b|describe\b|walk\s+me\s+through\b"
    r"|what\s+(?:happens|does|is\s+the\s+(?:process|purpose|point|rationale))\b"
    r"|tell\s+me\s+(?:about|more)\b"
    r"|can\s+you\s+(?:explain|describe|elaborate)\b"
    r"|in\s+what\s+way"
    r")",
    re.IGNORECASE,
)


class RuleQueryClassifier:
    """The default :class:`~core.ports.query_router.QueryRouterPort`.

    There is deliberately **no message-length rule**. An ablation over
    thresholds from 8 to 24 words showed length contributes exactly zero
    accuracy, while actively misrouting verbose-but-trivial lookups ("could you
    please just tell me what the name of the lead of this space is") to the
    expensive route. Length correlates with elaborateness, not with difficulty.
    """

    def classify(self, message: str) -> RoutingDecision:
        """Route ``message``. Never raises; unrecognised input routes to SIMPLE.

        Order matters. COMPLEX is checked before MODERATE because "how do X and
        Y compare?" opens like an explanation but needs the breadth of a
        comparison. CONVERSATIONAL is checked first and is the only route that
        skips retrieval, so it is also the only one with a hard gate in front
        of it.
        """
        if not message:
            return RoutingDecision(RouteClass.SIMPLE, "empty message")

        # Bounded FIRST, before any pass over the string — `strip()` on a
        # multi-megabyte message is itself an O(n) scan on the event loop.
        # Truncation can only ever move a message AWAY from the
        # retrieval-skipping route (a message long enough to be truncated is
        # far past the six-word small-talk limit), so it cannot cause the one
        # harmful misclassification.
        message = message[:MAX_CLASSIFIED_CHARS]

        if not message.strip():
            # Nothing to classify. Behave as today rather than guessing.
            return RoutingDecision(RouteClass.SIMPLE, "empty message")

        if self._is_conversational(message):
            return RoutingDecision(
                RouteClass.CONVERSATIONAL, "whole message is small talk",
            )
        if _COMPLEX_RE.search(message):
            return RoutingDecision(
                RouteClass.COMPLEX, "comparative or multi-hop marker",
            )
        if _MODERATE_RE.match(message):
            return RoutingDecision(RouteClass.MODERATE, "explanatory opener")
        return RoutingDecision(RouteClass.SIMPLE, "no marker matched (default)")

    @staticmethod
    def _is_conversational(message: str) -> bool:
        """Three gates, all of which must pass to skip retrieval.

        A question mark means the person wants an answer, whatever words they
        used to ask for it — so it disqualifies outright, before any pattern is
        consulted.
        """
        if "?" in message:
            return False
        if len(message.split()) > MAX_CONVERSATIONAL_WORDS:
            return False
        return bool(_CONVERSATIONAL_RE.match(message))


# Structural conformance, checked at import rather than left to a test that
# might not be run.
_: QueryRouterPort = RuleQueryClassifier()
