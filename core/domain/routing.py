"""What each route actually does to retrieval.

A route class on its own changes nothing — this is the table that turns a
classification into concrete retrieval settings.

**Both width and budget move together, and that is the whole point.** Widening
`n_results` alone is a no-op: at the deployed ingest chunk size of 9000
characters, the existing 20000-character context budget already admits only two
chunks, so asking retrieval for 10 instead of 5 changes nothing that reaches
the model. A "complex" route that only widened retrieval would look implemented
and do nothing. Every profile therefore states its budget alongside its width,
and a test asserts the *effective* chunk count actually differs.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.ports.query_router import RouteClass


@dataclass(frozen=True)
class RetrievalProfile:
    """Retrieval settings for one route.

    ``retrieve=False`` skips retrieval altogether — the only profile that does,
    and the only one whose mistakes are user-visible, which is why the rule
    that selects it is the strictest in the classifier.
    """

    retrieve: bool
    n_results: int
    score_threshold: float
    max_context_chars: int


#: Develop's current defaults, so a route that means "behave as today" can say
#: so by construction rather than by coincidence.
_DEFAULT_THRESHOLD = 0.3
_DEFAULT_N_RESULTS = 5
_DEFAULT_CONTEXT_CHARS = 20_000

#: Derived, not chosen:
#:
#: - **conversational** skips retrieval; the remaining fields are unused but
#:   kept at defaults so the dataclass has no meaningless values.
#: - **simple** narrows to 3. It must never be *slower* than today, so it may
#:   only go down from the default of 5.
#: - **moderate** is exactly develop's default — the route an unrecognised
#:   question falls back to behaves precisely as the service does now.
#: - **complex** widens to 10 **and** doubles the budget to 40000. The budget
#:   is what makes the widening real: at a 9000-char chunk size, 20000 admits
#:   2 chunks and 40000 admits 4, so complex genuinely sees more context. At
#:   the 2000-char size it is 10 vs 5. Strictly greater at both, which is what
#:   the inertness test asserts.
DEFAULT_ROUTING_TABLE: dict[RouteClass, RetrievalProfile] = {
    RouteClass.CONVERSATIONAL: RetrievalProfile(
        retrieve=False,
        n_results=_DEFAULT_N_RESULTS,
        score_threshold=_DEFAULT_THRESHOLD,
        max_context_chars=_DEFAULT_CONTEXT_CHARS,
    ),
    RouteClass.SIMPLE: RetrievalProfile(
        retrieve=True,
        n_results=3,
        score_threshold=_DEFAULT_THRESHOLD,
        max_context_chars=_DEFAULT_CONTEXT_CHARS,
    ),
    RouteClass.MODERATE: RetrievalProfile(
        retrieve=True,
        n_results=_DEFAULT_N_RESULTS,
        score_threshold=_DEFAULT_THRESHOLD,
        max_context_chars=_DEFAULT_CONTEXT_CHARS,
    ),
    RouteClass.COMPLEX: RetrievalProfile(
        retrieve=True,
        n_results=10,
        score_threshold=_DEFAULT_THRESHOLD,
        max_context_chars=40_000,
    ),
}


def effective_chunks(profile: RetrievalProfile, chunk_size: int) -> int:
    """How many chunks actually reach the model under this profile.

    Retrieval width is an upper bound; the context budget is the real one. This
    is the function that makes "did widening do anything?" answerable instead
    of assumed.
    """
    if not profile.retrieve:
        return 0
    if chunk_size <= 0:
        return profile.n_results
    return min(profile.n_results, profile.max_context_chars // chunk_size)
