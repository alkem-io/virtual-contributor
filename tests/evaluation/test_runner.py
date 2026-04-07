"""Tests for evaluation/runner.py — orchestration, failure continuation, aggregate computation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from evaluation.dataset import TestCase


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_test_cases(n: int = 3) -> list[TestCase]:
    return [
        TestCase(
            question=f"Question {i}?",
            expected_answer=f"Answer {i}",
            relevant_documents=[f"https://example.com/doc{i}"],
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# EvaluationRunner
# ---------------------------------------------------------------------------


class TestEvaluationRunner:
    @pytest.fixture
    def mock_pipeline_invoker(self):
        invoker = AsyncMock()
        invoker.invoke.return_value = (
            "Pipeline answer",
            ["retrieved context 1", "retrieved context 2"],
            [{"uri": "https://example.com/doc0", "title": "Doc", "score": 0.9}],
        )
        return invoker

    @pytest.fixture
    def mock_scorer(self):
        scorer = AsyncMock()
        scorer.score.return_value = {
            "faithfulness": 0.8,
            "answer_relevancy": 0.7,
            "context_precision": 0.6,
            "context_recall": 0.5,
        }
        return scorer

    async def test_runs_all_test_cases(self, mock_pipeline_invoker, mock_scorer, tmp_path):
        from evaluation.runner import EvaluationRunner

        cases = _make_test_cases(3)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        run = await runner.run(cases, plugin_type="guidance", label="test")

        assert run.test_case_count == 3
        assert run.success_count == 3
        assert run.failure_count == 0
        assert len(run.cases) == 3

    async def test_continues_on_failure(self, mock_pipeline_invoker, mock_scorer, tmp_path):
        """FR-010: Individual case failure should not stop the run."""
        from evaluation.runner import EvaluationRunner

        # Second invocation raises
        mock_pipeline_invoker.invoke.side_effect = [
            ("Answer 0", ["ctx"], []),
            RuntimeError("Pipeline timeout"),
            ("Answer 2", ["ctx"], []),
        ]
        mock_scorer.score.return_value = {
            "faithfulness": 0.8,
            "answer_relevancy": 0.7,
            "context_precision": 0.6,
            "context_recall": 0.5,
        }

        cases = _make_test_cases(3)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        run = await runner.run(cases, plugin_type="guidance", label="test")

        assert run.success_count == 2
        assert run.failure_count == 1
        assert run.cases[1].error is not None
        assert "Pipeline timeout" in run.cases[1].error

    async def test_persists_results_json(self, mock_pipeline_invoker, mock_scorer, tmp_path):
        from evaluation.runner import EvaluationRunner

        cases = _make_test_cases(2)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        run = await runner.run(cases, plugin_type="guidance", label="baseline")

        result_files = list(tmp_path.glob("*.json"))
        assert len(result_files) == 1
        data = json.loads(result_files[0].read_text())
        assert data["plugin_type"] == "guidance"
        assert data["label"] == "baseline"
        assert len(data["cases"]) == 2

    async def test_aggregate_computation(self, mock_pipeline_invoker, mock_scorer, tmp_path):
        from evaluation.runner import EvaluationRunner

        # Return different scores for different cases
        mock_scorer.score.side_effect = [
            {"faithfulness": 0.6, "answer_relevancy": 0.5, "context_precision": 0.4, "context_recall": 0.3},
            {"faithfulness": 0.8, "answer_relevancy": 0.7, "context_precision": 0.6, "context_recall": 0.5},
            {"faithfulness": 1.0, "answer_relevancy": 0.9, "context_precision": 0.8, "context_recall": 0.7},
        ]

        cases = _make_test_cases(3)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        run = await runner.run(cases, plugin_type="guidance")

        assert "faithfulness" in run.aggregate
        agg = run.aggregate["faithfulness"]
        assert agg.min == pytest.approx(0.6)
        assert agg.max == pytest.approx(1.0)
        assert agg.mean == pytest.approx(0.8)
        assert agg.median == pytest.approx(0.8)

    async def test_empty_retrieval_still_scored(self, mock_pipeline_invoker, mock_scorer, tmp_path):
        """Empty retrieval should produce low scores, not skip the case."""
        from evaluation.runner import EvaluationRunner

        mock_pipeline_invoker.invoke.return_value = ("Answer", [], [])
        mock_scorer.score.return_value = {
            "faithfulness": 0.1,
            "answer_relevancy": 0.2,
            "context_precision": 0.0,
            "context_recall": 0.0,
        }

        cases = _make_test_cases(1)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        run = await runner.run(cases, plugin_type="guidance")

        assert run.success_count == 1
        assert run.cases[0].scores is not None
        assert run.cases[0].scores.context_precision == 0.0

    async def test_judge_unreachable_records_error(self, mock_pipeline_invoker, mock_scorer, tmp_path):
        """Judge model unreachable should produce clear error without external API fallback."""
        from evaluation.runner import EvaluationRunner

        mock_scorer.score.side_effect = ConnectionError("Judge model unreachable")

        cases = _make_test_cases(1)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        run = await runner.run(cases, plugin_type="guidance")

        assert run.failure_count == 1
        assert "Judge model unreachable" in run.cases[0].error
