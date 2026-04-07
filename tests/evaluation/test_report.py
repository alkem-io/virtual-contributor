"""Tests for evaluation/report.py — comparison report computation and formatting."""

from __future__ import annotations

import pytest

from evaluation.report import (
    AggregateMetrics,
    ComparisonReport,
    EvaluationCase,
    EvaluationRun,
    MetricDelta,
    MetricScores,
    compute_comparison,
    format_comparison,
    format_run_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "20260406T143022_baseline",
    plugin_type: str = "guidance",
    agg_values: dict[str, float] | None = None,
) -> EvaluationRun:
    """Create a minimal EvaluationRun for testing."""
    if agg_values is None:
        agg_values = {
            "faithfulness": 0.82,
            "answer_relevancy": 0.78,
            "context_precision": 0.71,
            "context_recall": 0.68,
        }
    aggregate = {
        name: AggregateMetrics(mean=val, median=val, min=val - 0.1, max=val + 0.1)
        for name, val in agg_values.items()
    }
    return EvaluationRun(
        id=run_id,
        timestamp="2026-04-06T14:30:22Z",
        label="baseline",
        plugin_type=plugin_type,
        test_set_path="evaluation/golden/test_set.jsonl",
        test_case_count=50,
        success_count=48,
        failure_count=2,
        duration_seconds=842.5,
        aggregate=aggregate,
        cases=[
            EvaluationCase(
                index=0,
                question="What is Alkemio?",
                expected_answer="A platform",
                relevant_documents=["https://alkem.io"],
                pipeline_answer="Alkemio is a platform",
                scores=MetricScores(
                    faithfulness=0.92,
                    answer_relevancy=0.88,
                    context_precision=0.85,
                    context_recall=0.79,
                ),
                duration_seconds=4.2,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# MetricDelta computation
# ---------------------------------------------------------------------------


class TestComputeComparison:
    def test_computes_deltas(self):
        baseline = _make_run(
            "baseline",
            agg_values={"faithfulness": 0.80, "answer_relevancy": 0.70,
                        "context_precision": 0.60, "context_recall": 0.50},
        )
        current = _make_run(
            "current",
            agg_values={"faithfulness": 0.90, "answer_relevancy": 0.75,
                        "context_precision": 0.55, "context_recall": 0.60},
        )

        report = compute_comparison(baseline, current)

        assert report.baseline_id == "baseline"
        assert report.current_id == "current"
        assert len(report.deltas) == 4

        # faithfulness: +0.10 = +12.5%
        d = report.deltas["faithfulness"]
        assert d.baseline == pytest.approx(0.80)
        assert d.current == pytest.approx(0.90)
        assert d.absolute_delta == pytest.approx(0.10)
        assert d.percentage_change == pytest.approx(12.5)

        # context_precision: -0.05 = -8.33%
        d = report.deltas["context_precision"]
        assert d.absolute_delta == pytest.approx(-0.05)
        assert d.percentage_change == pytest.approx(-8.333, rel=1e-2)

    def test_handles_zero_baseline(self):
        baseline = _make_run(
            "baseline",
            agg_values={"faithfulness": 0.0, "answer_relevancy": 0.5,
                        "context_precision": 0.5, "context_recall": 0.5},
        )
        current = _make_run(
            "current",
            agg_values={"faithfulness": 0.5, "answer_relevancy": 0.5,
                        "context_precision": 0.5, "context_recall": 0.5},
        )
        report = compute_comparison(baseline, current)
        # Zero baseline → percentage_change should be 0.0 (no division error)
        assert report.deltas["faithfulness"].percentage_change == 0.0

    def test_summary_count(self):
        baseline = _make_run(
            "baseline",
            agg_values={"faithfulness": 0.5, "answer_relevancy": 0.5,
                        "context_precision": 0.5, "context_recall": 0.5},
        )
        current = _make_run(
            "current",
            agg_values={"faithfulness": 0.6, "answer_relevancy": 0.6,
                        "context_precision": 0.4, "context_recall": 0.5},
        )
        report = compute_comparison(baseline, current)

        improved = sum(1 for d in report.deltas.values() if d.absolute_delta > 0)
        regressed = sum(1 for d in report.deltas.values() if d.absolute_delta < 0)
        assert improved == 2
        assert regressed == 1


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatRunSummary:
    def test_contains_run_id(self):
        run = _make_run()
        output = format_run_summary(run)
        assert "20260406T143022_baseline" in output

    def test_contains_metric_values(self):
        run = _make_run()
        output = format_run_summary(run)
        assert "faithfulness" in output
        assert "0.820" in output

    def test_contains_failure_count(self):
        run = _make_run()
        output = format_run_summary(run)
        assert "Failures: 2/50" in output


class TestFormatComparison:
    def test_contains_metric_deltas(self):
        report = ComparisonReport(
            baseline_id="baseline",
            current_id="current",
            deltas={
                "faithfulness": MetricDelta(
                    baseline=0.80, current=0.90,
                    absolute_delta=0.10, percentage_change=12.5,
                ),
            },
        )
        output = format_comparison(report)
        assert "baseline" in output
        assert "current" in output
        assert "faithfulness" in output
        assert "12.5%" in output
