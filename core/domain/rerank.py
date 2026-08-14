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
    #: on lexical overlap — the blended scores are ``w`` for that passage and
    #: ``(1-w) + w*L0`` for the incumbent, where ``L0`` is the incumbent's own
    #: normalised lexical score. Promotion therefore needs::
    #:
    #:     w > 1 / (2 - L0)
    #:
    #: When the incumbent shares none of the query's wording (``L0 = 0``) that
    #: is ``w > 0.5`` — so at exactly 0.5 the two tie, the stable sort keeps
    #: the incumbent, and the feature provably cannot promote the passage it
    #: exists to promote.
    #:
    #: 0.6 clears that boundary for ``L0 < 1/3``. It is **not** a general
    #: guarantee: where the best-vector passage also carries moderate lexical
    #: overlap (``L0 = 0.4`` needs ``w > 0.625``) promotion still will not
    #: happen. The value is chosen to clear the strict case while keeping
    #: vector similarity in the lead; it is not tuned against a corpus.
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

        if len(vector_scores) != len(documents):
            # Stated rather than tolerated. Too few scores would raise an
            # opaque IndexError deep in the blend; too many would be silently
            # truncated by zip, hiding a caller bug that misaligns every
            # subsequent citation.
            raise ValueError(
                f"vector_scores has {len(vector_scores)} entries for "
                f"{len(documents)} documents; they must be parallel"
            )

        scores = blend(
            vector_scores, lexical_scores(query, documents), self._lexical_weight,
        )

        # Stable: equal scores keep input order, so a tie never reshuffles
        # results run to run. Sorting on the negated score rather than
        # reversing preserves that stability.
        order = sorted(range(len(documents)), key=lambda i: -scores[i])
        return order if top_k is None else order[:top_k]
