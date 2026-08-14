"""Pure helpers for opt-in hierarchy-aware expert retrieval.

The store only records the nearest subspace, not an ancestor chain.  These
helpers intentionally preserve that limitation instead of inventing a subtree
relationship that the persisted metadata cannot prove.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.ports.knowledge_store import QueryResult


# Chroma accepts one top-level logical operator.  The legacy type clause keeps
# old body-of-knowledge summaries useful while the embedding-type clauses pick
# up the newer orienting layer.
ORIENTING_WHERE: dict = {
    "$or": [
        {"embeddingType": {"$eq": "overview"}},
        {"embeddingType": {"$eq": "summary"}},
        {"type": {"$eq": "bodyOfKnowledgeSummary"}},
    ]
}

# These are deliberately exclusions.  A positive "chunk" filter would drop
# older collection entries whose embeddingType predates that field.
DETAIL_WHERE: dict = {
    "$and": [
        {"embeddingType": {"$ne": "overview"}},
        {"embeddingType": {"$ne": "summary"}},
        {"type": {"$ne": "bodyOfKnowledgeSummary"}},
    ]
}


@dataclass(frozen=True)
class BranchRef:
    """A typed stored branch key, retaining space/subspace distinction."""

    field: Literal["spaceId", "subspaceId"]
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("BranchRef value must be non-empty")


def branch_from_metadata(metadata: dict) -> BranchRef | None:
    """Select the nearest stored branch, never an inferred ancestor."""

    subspace_id = metadata.get("subspaceId")
    if isinstance(subspace_id, str) and subspace_id.strip():
        return BranchRef("subspaceId", subspace_id)
    space_id = metadata.get("spaceId")
    if isinstance(space_id, str) and space_id.strip():
        return BranchRef("spaceId", space_id)
    return None


def select_branches(
    result: QueryResult, *, score_threshold: float, max_branches: int
) -> list[BranchRef]:
    """Select relevant, semantically-scored branches in ranked order."""

    if max_branches < 1:
        return []
    distances = result.distances[0] if result.distances else []
    metadatas = result.metadatas[0] if result.metadatas else []
    selected: list[BranchRef] = []
    seen: set[BranchRef] = set()
    # Query results are rank ordered. Missing/lexical distances cannot prove a
    # semantic route, so they never select a branch.
    for index, metadata in enumerate(metadatas):
        if index >= len(distances):
            continue
        distance = distances[index]
        if distance is None or 1.0 - distance < score_threshold:
            continue
        branch = branch_from_metadata(metadata)
        if branch is None or branch in seen:
            continue
        selected.append(branch)
        seen.add(branch)
        if len(selected) >= max_branches:
            break
    return selected


def scoped_detail_where(branches: list[BranchRef]) -> dict | None:
    """Build a Chroma-valid detail predicate for selected typed branches."""

    if not branches:
        return None
    clauses = [{branch.field: {"$eq": branch.value}} for branch in branches]
    branch_clause = clauses[0] if len(clauses) == 1 else {"$or": clauses}
    return {"$and": [*DETAIL_WHERE["$and"], branch_clause]}
