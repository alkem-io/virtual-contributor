"""Port for deciding how much retrieval a question deserves.

Every question currently pays for the same retrieval work. "Thanks!" costs an
embedding call and a vector search it has no use for; "how do the goals of
subspace A and B relate?" gets the same narrow slice of context as "what is the
mission?". This port is where that judgement is made, before any retrieval
happens.

**Synchronous on purpose.** An ``async`` signature would invite a network call
inside the classifier, and a classifier that makes a network call defeats
itself: it would add a round trip to *every* question in order to save work on
*some*. Keeping the signature synchronous makes that mistake visible at review
rather than at runtime.

Primitives only — no store, no LLM, no adapter type appears here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class RouteClass(str, Enum):
    """How much retrieval work a question warrants.

    ``str`` mixin so a route can be logged and compared against a config value
    without conversion.
    """

    #: Small talk. No retrieval — there is nothing in a knowledge base that
    #: answers "thanks".
    CONVERSATIONAL = "conversational"
    #: A direct lookup. Narrow retrieval is enough.
    SIMPLE = "simple"
    #: Explanatory. Today's default breadth.
    MODERATE = "moderate"
    #: Comparative or multi-hop. Needs more context to answer at all.
    COMPLEX = "complex"


@dataclass(frozen=True)
class RoutingDecision:
    """A route and why it was chosen.

    ``reason`` exists so an operator reading logs can tell *why* a question was
    routed as it was — without it, a misrouted question is indistinguishable
    from a correctly-routed one that simply answered badly.
    """

    route: RouteClass
    reason: str


@runtime_checkable
class QueryRouterPort(Protocol):
    """Classifies a question into a route."""

    def classify(self, message: str) -> RoutingDecision:
        """Return the route for ``message``.

        Must never raise, never perform I/O, and never depend on anything but
        its argument. Callers treat classification as an optimisation: if it
        cannot decide, the answer is the route that behaves exactly as the
        service does today.
        """
        ...
