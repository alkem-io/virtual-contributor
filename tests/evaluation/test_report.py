"""Tests for evaluation/report.py — comparison report computation and formatting."""

from __future__ import annotations

import pytest
from evaluation.dataset import TestCase, canonical_test_set_digest, successful_case_digest

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
from plugins.expert.composition import expert_full_composition_fingerprint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "20260406T143022_baseline",
    plugin_type: str = "expert",
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
    case_input = TestCase(question="What is Alkemio?", expected_answer="A platform", relevant_documents=["https://alkem.io"])
    aggregate = {
        name: AggregateMetrics(mean=val, median=val, min=val, max=val)
        for name, val in agg_values.items()
    }
    mode = "hierarchical" if "current" in run_id else "flat"
    invariant = "a" * 64
    return EvaluationRun(
        id=run_id,
        timestamp="2026-04-06T14:30:22Z",
        label="baseline",
        plugin_type=plugin_type,
        test_set_path="evaluation/golden/test_set.jsonl",
        test_case_count=1,
        success_count=1,
        failure_count=0,
        duration_seconds=842.5,
        composition_fingerprint="matched-composition",
        composition_identity_version=6,
        hierarchy_mode=mode,
        test_set_digest=canonical_test_set_digest([case_input]),
        body_of_knowledge_digest="c" * 64,
        corpus_revision="reingest-2026-08-14",
        successful_case_digests=[successful_case_digest(case_input)],
        invariant_composition_fingerprint=invariant,
        full_composition_fingerprint=expert_full_composition_fingerprint(invariant, mode),
        aggregate=aggregate,
        cases=[
            EvaluationCase(
                index=0,
                question="What is Alkemio?",
                expected_answer="A platform",
                relevant_documents=["https://alkem.io"],
                pipeline_answer="Alkemio is a platform",
                scores=MetricScores(**agg_values),
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

    def test_rejects_comparison_when_effective_composition_differs(self):
        baseline, current = _make_run("baseline"), _make_run("current")
        current.invariant_composition_fingerprint = "e" * 64
        with pytest.raises(ValueError, match="invariant_composition_fingerprint differs"):
            compute_comparison(baseline, current)

    @pytest.mark.parametrize("missing", ["baseline", "current"])
    def test_rejects_comparison_when_a_fingerprint_is_missing(self, missing):
        baseline, current = _make_run("baseline"), _make_run("current")
        if missing == "baseline":
            baseline.invariant_composition_fingerprint = None
        else:
            current.invariant_composition_fingerprint = ""
        with pytest.raises(ValueError, match="complete v6 pairing identity"):
            compute_comparison(baseline, current)

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
        assert "Failures: 0/1" in output


def test_comparison_accepts_complete_expert_flat_to_on_pair():
    assert compute_comparison(_make_run("baseline"), _make_run("current")).deltas


def test_rejects_nan_case_and_aggregate_metrics():
    with pytest.raises(ValueError):
        MetricScores(faithfulness=float("nan"))
    with pytest.raises(ValueError):
        AggregateMetrics(mean=float("nan"), median=0, min=0, max=0)


def test_rejects_positive_and_negative_infinite_metrics():
    for value in (float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            MetricScores(context_precision=value)


def test_rejects_finite_metrics_outside_inclusive_unit_interval():
    for value in (-.01, 1.01, True, "0.5"):
        with pytest.raises(ValueError):
            MetricScores(context_recall=value)


def test_accepts_exact_zero_and_one_metric_boundaries():
    assert MetricScores(faithfulness=0, answer_relevancy=1).faithfulness == 0
    assert AggregateMetrics(mean=0, median=1, min=0, max=1).max == 1


def test_report_rejects_unknown_case_identity_version():
    from evaluation.case_identity import CASE_IDENTITY_VERSION
    assert CASE_IDENTITY_VERSION == "evaluation-case-identity/v1"
    run = _make_run("baseline")
    run.composition_identity_version = 5
    with pytest.raises(ValueError, match="v6"):
        compute_comparison(run, _make_run("current"))


def test_case_schema_extension_cannot_diverge_producer_and_verifier():
    from pydantic import BaseModel
    from evaluation.case_identity import evaluation_case_identity_payload
    class FutureCase(BaseModel):
        question: str
        expected_answer: str
        relevant_documents: list[str]
        required_future_field: str
    with pytest.raises(ValueError, match="schema"):
        evaluation_case_identity_payload(FutureCase(question="q", expected_answer="a", relevant_documents=["d"], required_future_field="x"))


def test_v6_comparison_accepts_equivalent_default_representation():
    assert compute_comparison(_make_run("baseline"), _make_run("current")).deltas


@pytest.mark.parametrize("mutation", ["plugin", "mode", "dataset", "bok", "corpus", "success", "invariant", "full", "failure", "legacy"])
def test_comparison_rejects_incomplete_or_mismatched_v4_identity(mutation):
    baseline, current = _make_run("baseline"), _make_run("current")
    if mutation == "plugin":
        current.plugin_type = "guidance"
    elif mutation == "mode":
        current.hierarchy_mode = "flat"
    elif mutation == "dataset":
        current.test_set_digest = "e" * 64
    elif mutation == "bok":
        current.body_of_knowledge_digest = "e" * 64
    elif mutation == "corpus":
        current.corpus_revision = "other-revision"
    elif mutation == "success":
        current.successful_case_digests = ["e" * 64]
    elif mutation == "invariant":
        current.invariant_composition_fingerprint = "e" * 64
    elif mutation == "full":
        current.full_composition_fingerprint = baseline.full_composition_fingerprint
    elif mutation == "failure":
        current.failure_count = 1
    else:
        baseline.invariant_composition_fingerprint = None
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def _reject_v4(mutation: str) -> None:
    baseline, current = _make_run("baseline"), _make_run("current")
    if mutation == "plugin":
        current.plugin_type = "guidance"
    elif mutation == "mode":
        current.hierarchy_mode = "flat"
    elif mutation == "dataset":
        current.test_set_digest = "e" * 64
    elif mutation == "bok":
        current.body_of_knowledge_digest = "e" * 64
    elif mutation == "corpus":
        current.corpus_revision = "other"
    elif mutation == "success":
        current.successful_case_digests = ["e" * 64]
    elif mutation == "invariant":
        current.invariant_composition_fingerprint = "e" * 64
    elif mutation == "equal_full":
        current.full_composition_fingerprint = baseline.full_composition_fingerprint
    elif mutation == "mode_full":
        current.full_composition_fingerprint = expert_full_composition_fingerprint(
            current.invariant_composition_fingerprint, "flat"
        )
    elif mutation == "legacy":
        baseline.invariant_composition_fingerprint = None
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_comparison_rejects_non_expert_or_wrong_mode_order():
    _reject_v4("plugin")
    _reject_v4("mode")


def test_comparison_rejects_test_set_identity_mismatch():
    _reject_v4("dataset")


def test_comparison_rejects_body_of_knowledge_identity_mismatch():
    _reject_v4("bok")


def test_comparison_rejects_missing_or_mismatched_corpus_revision():
    _reject_v4("corpus")


def test_comparison_rejects_failures_or_successful_case_mismatch():
    _reject_v4("success")
    baseline, current = _make_run("baseline"), _make_run("current")
    current.failure_count = 1
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_comparison_rejects_invariant_fingerprint_mismatch():
    _reject_v4("invariant")


def test_comparison_rejects_missing_or_equal_full_fingerprints():
    _reject_v4("equal_full")


def test_comparison_rejects_full_fingerprint_not_bound_to_mode():
    _reject_v4("mode_full")


def test_comparison_rejects_legacy_reports_without_v4_identity():
    _reject_v4("legacy")

@pytest.mark.parametrize("field", ["query_cap", "rewrite_cap", "attempts", "attempt_timeout", "deadline"])
def test_comparison_rejects_each_embedding_safety_control_mismatch(field):
    baseline, current = _make_run("baseline"), _make_run("current")
    current.invariant_composition_fingerprint = "e" * 64
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)

def test_comparison_rejects_pre_v5_composition_identity():
    baseline, current = _make_run("baseline"), _make_run("current")
    baseline.composition_identity_version = 4
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)

def test_comparison_rejects_incoherent_case_and_count_inventory():
    baseline, current = _make_run("baseline"), _make_run("current")
    current.success_count = 2
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)

def test_comparison_rejects_incomplete_or_failed_case_inventory():
    baseline, current = _make_run("baseline"), _make_run("current")
    current.cases[0].pipeline_answer = None
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)
    baseline, current = _make_run("baseline"), _make_run("current")
    current.cases[0].scores.faithfulness = None
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)

def test_comparison_rejects_noncanonical_sha256_identity():
    baseline, current = _make_run("baseline"), _make_run("current")
    current.test_set_digest = "UPPER"
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)

def test_comparison_recomputes_ordered_case_digests_and_metric_means():
    baseline, current = _make_run("baseline"), _make_run("current")
    current.successful_case_digests = ["e" * 64]
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)
    baseline, current = _make_run("baseline"), _make_run("current")
    current.aggregate["faithfulness"].mean = 0.0
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_root_readme_documents_equal_invariant_and_distinct_full_fingerprints():
    text = open("README.md", encoding="utf-8").read()
    normalized = " ".join(text.lower().split())
    assert "equal invariant fingerprints" in normalized
    assert "full fingerprints must be present, recomputable" in normalized
    assert "explicit modes, and different for flat versus hierarchical" in normalized
    assert "both full fingerprints equal" not in normalized


def test_expert_readme_documents_equal_invariant_and_distinct_full_fingerprints():
    text = open("plugins/expert/README.md", encoding="utf-8").read()
    normalized = " ".join(text.lower().split())
    assert "invariant fingerprints are equal" in normalized
    assert "both full fingerprints are present, recomputable from the invariant plus mode" in normalized
    assert "different for flat versus hierarchical" in normalized
    assert "both full fingerprints equal" not in normalized


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
