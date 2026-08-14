"""Blend the vector ranking with a lexical one and return the new order.

This is the whole re-ranking stage. It sits between retrieval and context
assembly, and it decides only *order* — never eligibility. Which passages are
good enough to use is still judged on the vector score, for a reason worth
stating: the blended score below is normalised over the candidate pool, so the
worst candidate always scores 0.0 and the best always 1.0, no matter how good
or bad either actually is. Threshold on that and a pool of excellent passages
would lose its worst member while a pool of terrible ones would keep its best.
It is a ranking signal and nothing else.

Imports nothing but stdlib and one sibling domain module. That is enforced by
a test, because it is what makes "no user content leaves the boundary" a
mechanical property of this path rather than a promise.
"""

from __future__ import annotations

from core.domain.lexical_score import lexical_scores


def _minmax(values: list[float]) -> list[float]:
    """Rescale to ``[0, 1]``, or to all zeros when every value is equal.

    Zero range means the signal separates nothing. Returning zeros says
    exactly that and lets the other component of the blend decide, whereas
    returning 0.5 would assert a middling opinion the data does not support.
    """
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high - low < 1e-12:
        return [0.0] * len(values)
    span = high - low
    return [(v - low) / span for v in values]


def blend(
    vector_scores: list[float],
    lexical: list[float],
    weight: float,
) -> list[float]:
    """Convex combination of the two normalised signals.

    ``weight`` is the lexical share: 0.0 is pure vector, 1.0 is pure lexical.
    Both sides are normalised first because they are not otherwise on a shared
    scale — and in guidance they are not even internally consistent, since the
    vector scores arrive from three separately-populated collections.
    """
    norm_vec = _minmax(vector_scores)
    norm_lex = _minmax(lexical)
    return [
        (1.0 - weight) * v + weight * lex
        for v, lex in zip(norm_vec, norm_lex)
    ]


class LexicalReranker:
    """Re-ranks by blending vector similarity with lexical overlap.

    The default implementation of :class:`~core.ports.reranker.RerankerPort`.
    A neural cross-encoder would be a second implementation behind the same
    port — this deployment has no GPU to run one on, so what ships is the
    stage and the seam, with a scorer that costs under a millisecond.
    """

    #: Lexical share of the blend. Above 0.5 on purpose, and not by taste.
    #:
    #: Min-max normalisation pins the best-vector candidate to exactly 1.0 and
    #: the worst to exactly 0.0. So for the case this feature exists for — the
    #: passage holding the query's terms is *worst* on vector distance and best
    #: on lexical overlap — the two blended scores come out as ``w`` and
    #: ``1-w``. They are equal at exactly 0.5, and the stable sort then keeps
    #: the incumbent ahead. At the arithmetic midpoint the feature provably
    #: cannot promote that passage however strong its match.
    #:
    #: 0.6 clears the boundary with margin while staying close enough to the
    #: middle that vector similarity still leads and lexical overlap corrects.
    DEFAULT_LEXICAL_WEIGHT = 0.6

    def __init__(self, lexical_weight: float = DEFAULT_LEXICAL_WEIGHT) -> None:
        self._lexical_weight = lexical_weight

    def rerank(
        self,
        query: str,
        documents: list[str],
        vector_scores: list[float],
        top_k: int | None = None,
    ) -> list[int]:
        """Return candidate indices best-first.

        At ``lexical_weight == 0.0`` this reproduces vector order exactly.
        That is the finer-grained rollback: an operator who has enabled
        re-ranking can neutralise its effect without also giving up the
        over-retrieval and top-K behaviour around it.
        """
        if not documents:
            return []

        scores = blend(
            vector_scores, lexical_scores(query, documents), self._lexical_weight,
        )

        # Stable: equal scores keep input order, so a tie never reshuffles
        # results run to run. Sorting on the negated score rather than
        # reversing preserves that stability.
        order = sorted(range(len(documents)), key=lambda i: -scores[i])
        return order if top_k is None else order[:top_k]
