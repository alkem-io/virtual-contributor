"""Tests for MAX_CONTEXT_CHARS enforcement logic."""

from __future__ import annotations

def _apply_context_budget(
    chunks: list[tuple[str, float]],
    max_context_chars: int,
) -> tuple[list[tuple[str, float]], int, int]:
    """Simulate context budget enforcement.

    Takes a list of (content, score) tuples sorted by score descending.
    Returns (kept_chunks, dropped_count, dropped_chars).
    """
    total_chars = sum(len(c) for c, _ in chunks)
    if total_chars <= max_context_chars:
        return chunks, 0, 0

    # Sort by score descending (should already be, but enforce)
    sorted_chunks = sorted(chunks, key=lambda x: x[1], reverse=True)
    kept = []
    accumulated = 0
    for content, score in sorted_chunks:
        if accumulated + len(content) > max_context_chars:
            break
        kept.append((content, score))
        accumulated += len(content)

    dropped_count = len(chunks) - len(kept)
    dropped_chars = total_chars - accumulated
    return kept, dropped_count, dropped_chars


class TestContextBudgetEnforcement:
    """Test context budget drops lowest-scoring chunks first."""

    def test_all_kept_when_under_budget(self) -> None:
        chunks = [("short", 0.9), ("text", 0.8), ("here", 0.7)]
        kept, dropped, _ = _apply_context_budget(chunks, max_context_chars=100)
        assert len(kept) == 3
        assert dropped == 0

    def test_drops_lowest_scoring_first(self) -> None:
        # 3 chunks: 10 chars each = 30 total. Budget = 20.
        chunks = [
            ("a" * 10, 0.9),
            ("b" * 10, 0.5),
            ("c" * 10, 0.3),
        ]
        kept, dropped, dropped_chars = _apply_context_budget(chunks, max_context_chars=20)
        assert len(kept) == 2
        assert dropped == 1
        assert dropped_chars == 10
        # The highest-scoring chunks should be kept
        scores = [s for _, s in kept]
        assert 0.9 in scores
        assert 0.5 in scores

    def test_empty_result_when_budget_very_small(self) -> None:
        chunks = [("a" * 100, 0.9)]
        kept, dropped, _ = _apply_context_budget(chunks, max_context_chars=1)
        assert len(kept) == 0
        assert dropped == 1

    def test_empty_chunks_returns_empty(self) -> None:
        kept, dropped, _ = _apply_context_budget([], max_context_chars=100)
        assert len(kept) == 0
        assert dropped == 0


class TestContextBudgetInExpertPlugin:
    """Test MAX_CONTEXT_CHARS enforcement in ExpertPlugin."""

    def test_accepts_max_context_chars(self, mock_llm, mock_knowledge_store) -> None:
        from plugins.expert.plugin import ExpertPlugin

        plugin = ExpertPlugin(
            llm=mock_llm,
            knowledge_store=mock_knowledge_store,
            n_results=5,
            score_threshold=0.0,
            max_context_chars=20000,
        )
        assert plugin._max_context_chars == 20000


class TestContextBudgetInGuidancePlugin:
    """Test MAX_CONTEXT_CHARS enforcement in GuidancePlugin."""

    def test_accepts_max_context_chars(self, mock_llm, mock_knowledge_store) -> None:
        from plugins.guidance.plugin import GuidancePlugin

        plugin = GuidancePlugin(
            llm=mock_llm,
            knowledge_store=mock_knowledge_store,
            n_results=5,
            score_threshold=0.0,
            max_context_chars=5000,
        )
        assert plugin._max_context_chars == 5000
