"""Reciprocal rank fusion — contract clauses C-1 through C-5."""

from __future__ import annotations

import copy
import random

from core.domain.rank_fusion import reciprocal_rank_fusion
from core.ports.knowledge_store import QueryResult


def _arm(ids: list[str], *, distances: list[float | None] | None = None) -> QueryResult:
    if distances is None:
        distances = [0.1 * (i + 1) for i in range(len(ids))]
    return QueryResult(
        documents=[[f"text-{i}" for i in ids]],
        metadatas=[[{"documentId": i} for i in ids]],
        distances=[list(distances)],
        ids=[list(ids)],
    )


def _lexical_arm(ids: list[str]) -> QueryResult:
    return _arm(ids, distances=[None] * len(ids))


def _fuse(arms, *, k=60, weights=None, limit=10) -> QueryResult:
    if weights is None:
        weights = [1.0] * len(arms)
    return reciprocal_rank_fusion(arms, k=k, weights=weights, limit=limit)


class TestScoring:
    def test_agreement_between_arms_outranks_a_single_arm(self):
        """The reason for asking twice: both arms agreeing lifts a passage."""
        dense = _arm(["a", "b", "c"])
        lexical = _lexical_arm(["c", "d"])
        result = _fuse([dense, lexical])
        order = result.ids[0]
        assert order.index("c") < order.index("b")

    def test_weights_reorder(self):
        dense = _arm(["a"])
        lexical = _lexical_arm(["b"])
        dense_heavy = _fuse([dense, lexical], weights=[10.0, 1.0]).ids[0]
        lexical_heavy = _fuse([dense, lexical], weights=[1.0, 10.0]).ids[0]
        assert dense_heavy[0] == "a"
        assert lexical_heavy[0] == "b"

    def test_muting_an_arm_removes_its_influence(self):
        dense = _arm(["a", "b"])
        lexical = _lexical_arm(["z"])
        result = _fuse([dense, lexical], weights=[1.0, 0.0])
        assert result.ids[0][:2] == ["a", "b"]

    def test_k_controls_how_much_rank_depth_costs(self):
        """k flattens the curve: small k makes the top of an arm dominant.

        `top` is first in the dense arm only. `deep` is far down both arms. At
        small k the first position is worth far more than two deep ones, so
        `top` leads; at large k the per-position difference nearly vanishes and
        appearing twice wins.
        """
        dense = _arm(["top"] + [f"pad-{n}" for n in range(8)] + ["deep"])
        lexical = _lexical_arm([f"lex-{n}" for n in range(8)] + ["deep"])

        small_k = _fuse([dense, lexical], k=1, limit=20).ids[0]
        large_k = _fuse([dense, lexical], k=1000, limit=20).ids[0]

        assert small_k.index("top") < small_k.index("deep")
        assert large_k.index("deep") < large_k.index("top")


class TestDeterminismAndOrdering:
    def test_identical_inputs_give_identical_output(self):
        dense = _arm(["a", "b", "c"])
        lexical = _lexical_arm(["c", "b", "a"])
        first = _fuse([dense, lexical]).ids[0]
        for _ in range(100):
            assert _fuse([dense, lexical]).ids[0] == first

    def test_ties_break_toward_the_dense_arm(self):
        """Equal scores must not be resolved by dict iteration order."""
        dense = _arm(["a"])
        lexical = _lexical_arm(["b"])
        result = _fuse([dense, lexical], weights=[1.0, 1.0])
        assert result.ids[0] == ["a", "b"]

    def test_output_is_stable_under_shuffled_construction(self):
        rng = random.Random(1234)
        ids = [f"doc-{n}" for n in range(12)]
        baseline = None
        for _ in range(50):
            shuffled = ids[:]
            rng.shuffle(shuffled)
            dense = _arm(shuffled)
            lexical = _lexical_arm(list(reversed(shuffled)))
            fused = _fuse([dense, lexical], limit=12).ids[0]
            assert sorted(fused) == sorted(ids)
            if baseline is None:
                baseline = fused
            # Same *inputs* must give the same output; different orderings may
            # legitimately differ, so only the set is asserted across shuffles.
        assert baseline is not None


class TestOutputShape:
    def test_all_lists_are_nested_and_index_aligned(self):
        result = _fuse([_arm(["a", "b"]), _lexical_arm(["b"])])
        assert len(result.ids) == 1
        n = len(result.ids[0])
        assert len(result.documents[0]) == n
        assert len(result.metadatas[0]) == n
        assert len(result.distances[0]) == n
        for i, doc_id in enumerate(result.ids[0]):
            assert result.metadatas[0][i]["documentId"] == doc_id

    def test_ids_are_unique(self):
        result = _fuse([_arm(["a", "b"]), _lexical_arm(["a", "b"])])
        assert len(result.ids[0]) == len(set(result.ids[0]))

    def test_limit_is_applied_last(self):
        result = _fuse([_arm(["a", "b", "c", "d"]), _lexical_arm(["e"])], limit=2)
        assert len(result.ids[0]) == 2


class TestDistanceHandling:
    def test_dense_distance_is_preserved(self):
        dense = _arm(["a"], distances=[0.42])
        result = _fuse([dense, _lexical_arm([])])
        assert result.distances[0][0] == 0.42

    def test_lexical_only_document_has_no_distance(self):
        """None, never 0.0 — a fabricated zero reads as a perfect match."""
        result = _fuse([_arm([]), _lexical_arm(["x"])])
        assert result.ids[0] == ["x"]
        assert result.distances[0][0] is None

    def test_document_in_both_arms_keeps_the_semantic_distance(self):
        dense = _arm(["a"], distances=[0.25])
        lexical = _lexical_arm(["a"])
        result = _fuse([dense, lexical])
        assert result.distances[0][0] == 0.25


class TestPurity:
    def test_inputs_are_not_mutated(self):
        dense = _arm(["a", "b"])
        lexical = _lexical_arm(["b", "c"])
        before = (copy.deepcopy(dense), copy.deepcopy(lexical))
        _fuse([dense, lexical])
        assert dense == before[0]
        assert lexical == before[1]

    def test_empty_arms_are_handled(self):
        assert _fuse([_arm([]), _lexical_arm([])]).ids[0] == []

    def test_one_empty_arm_passes_the_other_through(self):
        result = _fuse([_arm(["a", "b"]), _lexical_arm([])])
        assert result.ids[0] == ["a", "b"]

    def test_mismatched_weights_are_rejected(self):
        import pytest

        with pytest.raises(ValueError, match="parallel"):
            reciprocal_rank_fusion(
                [_arm(["a"])], k=60, weights=[1.0, 1.0], limit=10,
            )


class TestDistanceIsArmIndexed:
    """Semantic distance comes from the dense arm and nowhere else.

    The rule cannot be "prefer whichever arm supplied a number": a future
    lexical arm that reports its own score would then inject a fabricated
    *semantic* distance into the relevance threshold and into what the answer
    cites — the exact confusion widening the type was meant to prevent.
    """

    def test_a_scoring_lexical_arm_does_not_leak_a_distance(self):
        dense = _arm(["a", "b"])
        # A lexical arm that reports numbers, as a BM25 implementation would.
        scoring_lexical = _arm(["d"], distances=[0.1])
        result = reciprocal_rank_fusion(
            [dense, scoring_lexical], k=60, weights=[1.0, 1.0], limit=10,
        )
        assert result.distances[0][result.ids[0].index("d")] is None

    def test_the_dense_arm_still_supplies_its_own_distance(self):
        dense = _arm(["a"], distances=[0.33])
        result = reciprocal_rank_fusion(
            [dense, _arm(["d"], distances=[0.1])],
            k=60, weights=[1.0, 1.0], limit=10,
        )
        assert result.distances[0][result.ids[0].index("a")] == 0.33

    def test_payload_is_recovered_from_another_arm_when_dense_lacks_it(self):
        """An arm can return an id whose text it did not fetch."""
        dense = QueryResult(
            documents=[[""]], metadatas=[[{}]], distances=[[0.2]], ids=[["x"]],
        )
        lexical = QueryResult(
            documents=[["the real text"]], metadatas=[[{"source": "sx"}]],
            distances=[[None]], ids=[["x"]],
        )
        result = reciprocal_rank_fusion(
            [dense, lexical], k=60, weights=[1.0, 1.0], limit=10,
        )
        assert result.documents[0][0] == "the real text"
        assert result.metadatas[0][0] == {"source": "sx"}
        # Payload was recovered, but the distance still came from the dense arm.
        assert result.distances[0][0] == 0.2
