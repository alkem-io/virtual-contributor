"""Pure contract tests for hierarchy route and detail predicates."""

from core.domain.hierarchy_retrieval import (
    DETAIL_WHERE,
    ORIENTING_WHERE,
    BranchRef,
    branch_from_metadata,
    scoped_detail_where,
    select_branches,
)
from core.ports.knowledge_store import QueryResult


def _result(metadatas, distances):
    return QueryResult([['x'] * len(metadatas)], [metadatas], [distances], [['i'] * len(metadatas)])


def test_orienting_accepts_overview_and_summary() -> None:
    assert {"embeddingType": {"$eq": "overview"}} in ORIENTING_WHERE["$or"]
    assert {"embeddingType": {"$eq": "summary"}} in ORIENTING_WHERE["$or"]


def test_orienting_accepts_legacy_body_of_knowledge_summary() -> None:
    assert {"type": {"$eq": "bodyOfKnowledgeSummary"}} in ORIENTING_WHERE["$or"]


def test_orienting_excludes_detail_by_not_selecting_chunk() -> None:
    assert {"embeddingType": {"$eq": "chunk"}} not in ORIENTING_WHERE["$or"]


def test_detail_is_exclusion_shaped_for_legacy_content() -> None:
    assert {"embeddingType": {"$ne": "summary"}} in DETAIL_WHERE["$and"]


def test_detail_keeps_overview_as_answerable_content() -> None:
    # Overview rows are primary content (a space/subspace description), not
    # a derived Stage-1-only artifact, so Stage 2 must not exclude them.
    assert {"embeddingType": {"$ne": "overview"}} not in DETAIL_WHERE["$and"]


def test_detail_excludes_legacy_body_of_knowledge_summary() -> None:
    assert {"type": {"$ne": "bodyOfKnowledgeSummary"}} in DETAIL_WHERE["$and"]


def test_overview_and_summary_are_both_distinct_routing_inputs() -> None:
    values = {next(iter(clause.values())).get("$eq") for clause in ORIENTING_WHERE["$or"] if "embeddingType" in clause}
    assert values == {"overview", "summary"}


def test_branch_prefers_nearest_subspace() -> None:
    assert branch_from_metadata({"spaceId": "root", "subspaceId": "near"}) == BranchRef("subspaceId", "near")


def test_branch_uses_root_space_when_no_subspace() -> None:
    assert branch_from_metadata({"spaceId": "root"}) == BranchRef("spaceId", "root")


def test_branch_missing_returns_none() -> None:
    assert branch_from_metadata({"spaceId": ""}) is None


def test_branch_skips_missing_distances_and_threshold_failures() -> None:
    result = _result([{"spaceId": "a"}, {"spaceId": "b"}, {"spaceId": "c"}], [None, 0.8, 0.1])
    assert select_branches(result, score_threshold=0.3, max_branches=3) == [BranchRef("spaceId", "c")]


def test_branch_deduplicates_in_relevance_order() -> None:
    result = _result([{"spaceId": "a"}, {"spaceId": "a"}, {"subspaceId": "b"}], [0.1, 0.2, 0.3])
    assert select_branches(result, score_threshold=0.3, max_branches=3) == [BranchRef("subspaceId", "b")]


def test_branch_caps_at_three() -> None:
    result = _result([{"spaceId": str(i)} for i in range(4)], [0.1] * 4)
    assert len(select_branches(result, score_threshold=0.3, max_branches=3)) == 3


def test_branch_canonicalizes_specific_subspaces_before_cap() -> None:
    result = _result(
        [{"spaceId": "r1"}, {"spaceId": "r2"}, {"spaceId": "r3"}, {"spaceId": "root", "subspaceId": "precise"}],
        [0.1, 0.1, 0.1, 0.1],
    )
    assert select_branches(result, score_threshold=0.3, max_branches=3) == [
        BranchRef("subspaceId", "precise"),
    ]


def test_scoped_single_branch_is_not_store_invalid_or() -> None:
    where = scoped_detail_where([BranchRef("subspaceId", "a")])
    assert where is not None and {"subspaceId": {"$eq": "a"}} in where["$and"]
    assert "$or" not in where["$and"][-1]


def test_scoped_multiple_branches_uses_typed_or() -> None:
    where = scoped_detail_where([BranchRef("subspaceId", "a"), BranchRef("subspaceId", "b")])
    assert where is not None and where["$and"][-1] == {"$or": [{"subspaceId": {"$eq": "a"}}, {"subspaceId": {"$eq": "b"}}]}


def test_scoped_root_only_is_unusable_for_descendant_safe_routing() -> None:
    assert scoped_detail_where([BranchRef("spaceId", "root")]) is None
