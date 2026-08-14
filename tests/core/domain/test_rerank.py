"""Re-ranking: the contract clauses C-1..C-7, plus the ordering behaviour.

Several of these look pedantic and are not. C-1 (bijection) is what stops a
caller silently losing or duplicating a passage; C-4 is the rollback
guarantee; C-3 is what makes an answer reproducible when someone asks the same
question twice.
"""

from __future__ import annotations

import math
import random
import time

from core.domain.rerank import LexicalReranker, _minmax, blend
from core.ports.reranker import RerankerPort


def _vector_order(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: -scores[i])


class TestPort:
    def test_port_is_runtime_checkable(self) -> None:
        assert isinstance(LexicalReranker(), RerankerPort)


class TestMinMax:
    def test_rescales_to_unit_interval(self) -> None:
        assert _minmax([1.0, 2.0, 3.0]) == [0.0, 0.5, 1.0]

    def test_zero_range_yields_zeros_not_halves(self) -> None:
        """All-equal means "this signal separates nothing" — say so.

        0.5 would assert a middling opinion the data does not support, and
        would then contribute half its weight to every blended score.
        """
        assert _minmax([0.7, 0.7, 0.7]) == [0.0, 0.0, 0.0]

    def test_empty(self) -> None:
        assert _minmax([]) == []

    def test_never_produces_nan(self) -> None:
        for values in ([0.0, 0.0], [1e-15, 1e-15], [-1.0, -1.0], [0.5]):
            assert not any(math.isnan(v) for v in _minmax(values))


class TestBlend:
    def test_weight_zero_is_pure_vector(self) -> None:
        assert blend([0.0, 1.0], [1.0, 0.0], 0.0) == [0.0, 1.0]

    def test_weight_one_is_pure_lexical(self) -> None:
        assert blend([0.0, 1.0], [1.0, 0.0], 1.0) == [1.0, 0.0]


class TestContractClauses:
    """The clauses from contracts/rerank-port.md."""

    def _candidates(self) -> tuple[str, list[str], list[float]]:
        docs = [f"a page about spaces and members, number {i}" for i in range(20)]
        docs[7] = "to invite members to a space, open settings and click invite"
        return (
            "how do I invite members to a space",
            docs,
            [0.9 - 0.01 * i for i in range(20)],
        )

    def test_c1_result_is_a_bijection(self) -> None:
        query, docs, vec = self._candidates()
        order = LexicalReranker(0.5).rerank(query, docs, vec)
        assert sorted(order) == list(range(len(docs)))

    def test_c2_top_k_is_a_prefix_of_the_full_ordering(self) -> None:
        query, docs, vec = self._candidates()
        reranker = LexicalReranker(0.5)
        assert reranker.rerank(query, docs, vec, top_k=5) == (
            reranker.rerank(query, docs, vec)[:5]
        )

    def test_c3_deterministic_over_fifty_runs(self) -> None:
        query, docs, vec = self._candidates()
        reranker = LexicalReranker(0.5)
        first = reranker.rerank(query, docs, vec)
        assert all(reranker.rerank(query, docs, vec) == first for _ in range(50))

    def test_c4_weight_zero_equals_vector_order_over_200_random_cases(self) -> None:
        """The rollback guarantee, and the reason it is tested this hard.

        An operator who has enabled re-ranking must be able to neutralise its
        effect by weight alone. If this drifts, that escape hatch is gone.
        """
        rng = random.Random(20260814)
        reranker = LexicalReranker(0.0)
        for _ in range(200):
            n = rng.randint(1, 30)
            docs = [f"candidate text {rng.random()}" for _ in range(n)]
            vec = [rng.random() for _ in range(n)]
            assert reranker.rerank("invite members space", docs, vec) == _vector_order(vec)

    def test_c5_degenerate_inputs_never_raise(self) -> None:
        reranker = LexicalReranker(0.5)
        assert reranker.rerank("q", [], []) == []
        assert reranker.rerank("", ["a"], [0.5]) == [0]
        assert reranker.rerank("   ", ["a"], [0.5]) == [0]
        assert sorted(reranker.rerank("q", ["a", "b"], [0.5, 0.5])) == [0, 1]
        assert sorted(reranker.rerank("x", ["x", "x"], [0.1, 0.9])) == [0, 1]

    def test_c6_ties_resolve_to_input_order(self) -> None:
        # Identical documents and identical vector scores: nothing separates
        # them, so the original order must survive.
        order = LexicalReranker(0.5).rerank("zzz", ["a", "b", "c"], [0.5, 0.5, 0.5])
        assert order == [0, 1, 2]

    def test_c7_top_twenty_rerank_is_well_under_100ms(self) -> None:
        rng = random.Random(1)
        docs = ["lorem ipsum dolor sit amet consectetur " * 50 for _ in range(20)]
        vec = [rng.random() for _ in range(20)]
        reranker = LexicalReranker(0.5)

        start = time.perf_counter()
        for _ in range(20):
            reranker.rerank("invite members to a space", docs, vec)
        per_call_ms = (time.perf_counter() - start) * 1000 / 20

        # The story's budget is 100ms. Asserting well under it leaves headroom
        # for a loaded CI box without making the test meaningless.
        assert per_call_ms < 50, f"{per_call_ms:.2f}ms exceeds the budget"


class TestOrderingBehaviour:
    def test_term_matching_chunk_beats_generic_chunks_with_better_distance(self) -> None:
        """US1-AS1 — the scenario the story exists for."""
        docs = [
            "Alkemio is a platform for collaboration on societal challenges.",
            "Our mission is to enable collective action across society.",
            "To invite members to a space, open Space settings and click Invite.",
            "Alkemio brings together diverse stakeholders.",
        ]
        vec = [0.90, 0.88, 0.55, 0.86]  # the answer has the WORST distance
        order = LexicalReranker().rerank("how do I invite members to a space", docs, vec)
        assert order.index(2) < order.index(0)
        assert order.index(2) < order.index(1)

    def test_default_weight_clears_the_normalisation_boundary(self) -> None:
        """The default must be strictly above 0.5, and this is why.

        Min-max pins the best-vector candidate to 1.0 and the worst to 0.0. So
        when the term-matching passage is worst on vector and best on lexical,
        the blended scores are exactly ``w`` and ``1-w``: equal at 0.5, and the
        stable sort then keeps the incumbent ahead. At the midpoint the feature
        provably cannot promote that passage however strong its match.

        Pinned as a test because a future "let's default to the middle" would
        look reasonable and would silently disable US1.
        """
        assert LexicalReranker.DEFAULT_LEXICAL_WEIGHT > 0.5

        docs = ["a generic page about spaces", "how to invite members to a space"]
        vec = [0.90, 0.55]  # gold is worst on vector
        query = "how do I invite members to a space"

        # At exactly 0.5 the scores tie and input order wins: gold stays last.
        assert LexicalReranker(0.5).rerank(query, docs, vec) == [0, 1]
        # Above the boundary the lexical verdict is allowed to decide.
        assert LexicalReranker(0.51).rerank(query, docs, vec) == [1, 0]
        assert LexicalReranker().rerank(query, docs, vec) == [1, 0]

    def test_no_term_overlap_falls_back_to_vector_order(self) -> None:
        """US1-AS4 — no lexical signal must mean no opinion, not noise."""
        docs = ["completely unrelated", "also unrelated", "still unrelated"]
        vec = [0.5, 0.9, 0.4]
        assert LexicalReranker(0.5).rerank("zzz qqq", docs, vec) == _vector_order(vec)

    def test_top_k_truncates(self) -> None:
        docs = [f"doc {i}" for i in range(10)]
        vec = [0.5] * 10
        assert len(LexicalReranker(0.5).rerank("doc", docs, vec, top_k=3)) == 3

    def test_top_k_larger_than_candidates_returns_all(self) -> None:
        order = LexicalReranker(0.5).rerank("doc", ["a", "b"], [0.5, 0.6], top_k=99)
        assert sorted(order) == [0, 1]
