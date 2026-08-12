"""Truth-table coverage for the canonical retrieval metadata filters."""

from __future__ import annotations

import pytest

from core.domain.retrieval_filters import FACTUAL_WHERE, SUMMARIES_WHERE
from tests.conftest import MockKnowledgeStorePort


ENTRIES = [
    ("E1", {"embeddingType": "chunk", "type": "knowledge"}, True, False),
    ("E2", {"embeddingType": "summary", "type": "knowledge"}, False, True),
    (
        "E3",
        {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary"},
        False,
        True,
    ),
    ("E4", {"embeddingType": "chunk", "type": "knowledge"}, True, False),
    ("E5", {"embeddingType": "summary", "type": "knowledge"}, False, True),
    ("E6", {"type": "bodyOfKnowledgeSummary"}, False, True),
    (
        "E7",
        {"embeddingType": "summary", "type": "bodyOfKnowledgeSummary"},
        False,
        True,
    ),
    ("E8", {"type": "knowledge"}, True, False),
    ("E9", {"type": "bodyOfKnowledgeSummary"}, False, True),
]


def _matches(metadata: dict, where: dict) -> bool:
    """Evaluate the canonical Chroma filter subset with missing-key semantics."""
    if "$and" in where:
        return all(_matches(metadata, clause) for clause in where["$and"])
    if "$or" in where:
        return any(_matches(metadata, clause) for clause in where["$or"])
    key, condition = next(iter(where.items()))
    operator, expected = next(iter(condition.items()))
    if operator == "$eq":
        return key in metadata and metadata[key] == expected
    if operator == "$ne":
        return key not in metadata or metadata[key] != expected
    raise AssertionError(f"unexpected operator: {operator}")


@pytest.mark.parametrize("entry_id,metadata,factual,summaries", ENTRIES)
def test_canonical_filters_match_the_full_generation_truth_table(
    entry_id: str, metadata: dict, factual: bool, summaries: bool
) -> None:
    assert _matches(metadata, FACTUAL_WHERE) is factual, entry_id
    assert _matches(metadata, SUMMARIES_WHERE) is summaries, entry_id
    assert factual is not summaries, entry_id


async def test_summaries_and_unfiltered_queries_preserve_both_retrieval_modes() -> None:
    store = MockKnowledgeStorePort()
    await store.ingest(
        "mixed",
        [entry_id for entry_id, _, _, _ in ENTRIES],
        [metadata for _, metadata, _, _ in ENTRIES],
        [entry_id.lower() for entry_id, _, _, _ in ENTRIES],
    )

    summaries = await store.query(
        "mixed", ["overview"], 9, where=SUMMARIES_WHERE
    )
    unfiltered = await store.query("mixed", ["overview"], 9)

    assert summaries.documents == [["E2", "E3", "E5", "E6", "E7", "E9"]]
    assert unfiltered.documents == [[entry_id for entry_id, _, _, _ in ENTRIES]]
