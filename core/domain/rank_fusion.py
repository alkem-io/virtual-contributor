"""Combine several rankings of the same corpus into one.

Reciprocal Rank Fusion consumes **positions, not scores**. That matters here:
the two arms measure different things in incomparable units — one reports a
vector distance, the other reports only that a passage contains a word, with no
distance at all. Normalising those onto a shared scale would mean inventing a
number for the second. Ranks are the one thing both arms genuinely have.

A document found by both arms scores the sum of its two contributions, so
agreement between arms is what lifts a passage — which is the whole point of
asking twice.

Pure: no store, no adapter, no clock, no randomness, and the inputs are left
untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.ports.knowledge_store import QueryResult

#: Index of the dense arm in the ``arms`` argument. Fixed by convention so the
#: tie-break can prefer the semantically-ranked arm.
_DENSE_ARM = 0

#: Rank standing in for "absent from this arm" when breaking ties. Larger than
#: any real rank, so a document present in an arm always precedes one that is
#: not.
_ABSENT = float("inf")


@dataclass(frozen=True)
class _Candidate:
    """One document's standing across every arm."""

    doc_id: str
    score: float
    dense_rank: float
    lexical_rank: float
    document: str
    metadata: dict
    distance: float | None

    def sort_key(self) -> tuple:
        """Total order: score, then dense rank, then lexical rank, then id.

        Every component is needed for the result to be reproducible. Ordering
        by score alone would leave ties resolved by dict iteration order, so
        the same inputs could answer differently between runs.
        """
        return (-self.score, self.dense_rank, self.lexical_rank, self.doc_id)


def reciprocal_rank_fusion(
    arms: list[QueryResult],
    *,
    k: int,
    weights: list[float],
    limit: int,
) -> QueryResult:
    """Fuse per-arm rankings into a single ranked result.

    ``arms[0]`` is the dense arm by convention. ``weights`` is parallel to
    ``arms``. A document keeps the distance the dense arm reported for it, or
    ``None`` when only a lexical arm found it — never a stand-in number, which
    downstream code would read as a real similarity.
    """
    if len(weights) != len(arms):
        raise ValueError(
            f"weights has {len(weights)} entries for {len(arms)} arms — "
            "they must be parallel"
        )

    scores: dict[str, float] = {}
    ranks: dict[str, dict[int, int]] = {}
    payload: dict[str, tuple[str, dict, float | None]] = {}

    for arm_index, (arm, weight) in enumerate(zip(arms, weights)):
        ids = arm.ids[0] if arm.ids else []
        documents = arm.documents[0] if arm.documents else []
        metadatas = arm.metadatas[0] if arm.metadatas else []
        distances = arm.distances[0] if arm.distances else []

        for rank, doc_id in enumerate(ids):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank + 1)
            ranks.setdefault(doc_id, {})[arm_index] = rank

            document = documents[rank] if rank < len(documents) else ""
            metadata = metadatas[rank] if rank < len(metadatas) else {}
            distance = distances[rank] if rank < len(distances) else None

            existing = payload.get(doc_id)
            if existing is None:
                payload[doc_id] = (document, metadata, distance)
            elif existing[2] is None and distance is not None:
                # A later arm supplied the semantic distance an earlier one
                # could not. Prefer the real number over the absence.
                payload[doc_id] = (document or existing[0],
                                   metadata or existing[1],
                                   distance)

    candidates = []
    for doc_id, score in scores.items():
        per_arm = ranks[doc_id]
        document, metadata, distance = payload[doc_id]
        candidates.append(_Candidate(
            doc_id=doc_id,
            score=score,
            dense_rank=per_arm.get(_DENSE_ARM, _ABSENT),
            lexical_rank=min(
                (r for a, r in per_arm.items() if a != _DENSE_ARM),
                default=_ABSENT,
            ),
            document=document,
            metadata=metadata,
            distance=distance,
        ))

    candidates.sort(key=_Candidate.sort_key)
    kept = candidates[:limit]

    return QueryResult(
        documents=[[c.document for c in kept]],
        metadatas=[[c.metadata for c in kept]],
        distances=[[c.distance for c in kept]],
        ids=[[c.doc_id for c in kept]],
    )
