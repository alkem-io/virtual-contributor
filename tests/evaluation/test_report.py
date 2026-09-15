"""Tests for evaluation/report.py — comparison report computation and formatting."""

from __future__ import annotations

from pathlib import Path

import pytest
from evaluation.dataset import (
    TestCase,
    canonical_test_set_digest,
    successful_case_digest,
)

from evaluation.assertions import AssertionOutcome
from evaluation.report import (
    AggregateMetrics,
    ComparisonReport,
    EvaluationCase,
    EvaluationRun,
    ExactMatchDelta,
    ExactMatchSummary,
    MetricDelta,
    MetricScores,
    compute_comparison,
    compute_exact_match_summary,
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
    case_input = TestCase(
        question="What is Alkemio?",
        expected_answer="A platform",
        relevant_documents=["https://alkem.io"],
    )
    aggregate = {
        name: AggregateMetrics(mean=val, median=val, min=val, max=val)
        for name, val in agg_values.items()
    }
    mode = "hierarchical" if "current" in run_id else "flat"
    invariant = "a" * 64
    from evaluation.case_identity import CASE_IDENTITY_VERSION

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
        composition_identity_version=7,
        case_identity_version=CASE_IDENTITY_VERSION,
        hierarchy_mode=mode,
        test_set_digest=canonical_test_set_digest([case_input]),
        body_of_knowledge_digest="c" * 64,
        corpus_revision="reingest-2026-08-14",
        successful_case_digests=[successful_case_digest(case_input)],
        invariant_composition_fingerprint=invariant,
        full_composition_fingerprint=expert_full_composition_fingerprint(
            invariant, mode
        ),
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
            agg_values={
                "faithfulness": 0.80,
                "answer_relevancy": 0.70,
                "context_precision": 0.60,
                "context_recall": 0.50,
            },
        )
        current = _make_run(
            "current",
            agg_values={
                "faithfulness": 0.90,
                "answer_relevancy": 0.75,
                "context_precision": 0.55,
                "context_recall": 0.60,
            },
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
            agg_values={
                "faithfulness": 0.0,
                "answer_relevancy": 0.5,
                "context_precision": 0.5,
                "context_recall": 0.5,
            },
        )
        current = _make_run(
            "current",
            agg_values={
                "faithfulness": 0.5,
                "answer_relevancy": 0.5,
                "context_precision": 0.5,
                "context_recall": 0.5,
            },
        )
        report = compute_comparison(baseline, current)
        # Zero baseline → percentage_change should be 0.0 (no division error)
        assert report.deltas["faithfulness"].percentage_change == 0.0

    def test_rejects_comparison_when_effective_composition_differs(self):
        baseline, current = _make_run("baseline"), _make_run("current")
        current.invariant_composition_fingerprint = "e" * 64
        with pytest.raises(
            ValueError, match="invariant_composition_fingerprint differs"
        ):
            compute_comparison(baseline, current)

    @pytest.mark.parametrize("missing", ["baseline", "current"])
    def test_rejects_comparison_when_a_fingerprint_is_missing(self, missing):
        baseline, current = _make_run("baseline"), _make_run("current")
        if missing == "baseline":
            baseline.invariant_composition_fingerprint = None
        else:
            current.invariant_composition_fingerprint = ""
        with pytest.raises(ValueError, match="complete v7 pairing identity"):
            compute_comparison(baseline, current)

    def test_summary_count(self):
        baseline = _make_run(
            "baseline",
            agg_values={
                "faithfulness": 0.5,
                "answer_relevancy": 0.5,
                "context_precision": 0.5,
                "context_recall": 0.5,
            },
        )
        current = _make_run(
            "current",
            agg_values={
                "faithfulness": 0.6,
                "answer_relevancy": 0.6,
                "context_precision": 0.4,
                "context_recall": 0.5,
            },
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

    def test_no_checked_assertions_is_reported_judge_only_not_silently_passing(self):
        """The case with no assertion_outcome at all (the default _make_run
        fixture) must render as judge-only, never folded into a pass rate."""
        run = _make_run()
        output = format_run_summary(run)
        assert "No checkable cases in this run" in output
        assert "judge-only: 0" in output
        # Never claims a pass rate for a run with nothing checked.
        assert "Pass rate" not in output

    def test_checked_assertions_render_pass_rate_separately_from_metrics(self):
        run = _make_run()
        run.cases[0].assertion_outcome = AssertionOutcome(status="passed", missing=[])
        output = format_run_summary(run)
        assert "Pass rate: 1/1 (100.0%)" in output
        assert "not-applicable (no derivable fact): 0" in output

    def test_unanchored_case_among_others_counts_as_not_applicable_not_passed(self):
        run = _make_run()
        run.cases[0].assertion_outcome = AssertionOutcome(status="not_applicable", missing=[])
        output = format_run_summary(run)
        assert "No checkable cases in this run" in output
        assert "judge-only: 1" in output

    def test_category_scope_is_rendered(self):
        run = _make_run()
        run.category_scope = "documentation"
        output = format_run_summary(run)
        assert "Category scope: documentation" in output
        assert "WARNING" not in output

    def test_category_scope_missing_body_of_knowledge_warns(self):
        run = _make_run()
        run.category_scope = "building-alkemio"
        run.category_scope_missing_body_of_knowledge = True
        output = format_run_summary(run)
        assert "WARNING" in output
        assert "--body-of-knowledge-id" in output

    def test_no_category_scope_omits_the_section(self):
        run = _make_run()
        output = format_run_summary(run)
        assert "Category scope" not in output


class TestComputeExactMatchSummary:
    def _case(self, status: str) -> EvaluationCase:
        return EvaluationCase(
            index=0,
            question="Q",
            expected_answer="A",
            relevant_documents=[],
            pipeline_answer="answer",
            scores=MetricScores(
                faithfulness=0.8, answer_relevancy=0.7,
                context_precision=0.6, context_recall=0.5,
            ),
            assertion_outcome=AssertionOutcome(status=status, missing=[]),
            duration_seconds=1.0,
        )

    def test_tallies_each_status_into_its_own_bucket(self):
        cases = [self._case("passed"), self._case("passed"), self._case("failed"), self._case("not_applicable")]
        summary = compute_exact_match_summary(cases)
        assert summary.passed == 2
        assert summary.failed == 1
        assert summary.not_applicable == 1
        assert summary.checked == 3

    def test_pass_rate_excludes_not_applicable_from_denominator(self):
        cases = [self._case("passed"), self._case("not_applicable"), self._case("not_applicable")]
        summary = compute_exact_match_summary(cases)
        assert summary.checked == 1
        assert summary.pass_rate == 1.0

    def test_pass_rate_is_none_when_nothing_checked(self):
        summary = compute_exact_match_summary([self._case("not_applicable")])
        assert summary.checked == 0
        assert summary.pass_rate is None

    def test_case_with_no_outcome_at_all_counts_toward_neither_bucket(self):
        case = EvaluationCase(
            index=0, question="Q", expected_answer="A", relevant_documents=[],
            error="pipeline failed", duration_seconds=1.0,
        )
        summary = compute_exact_match_summary([case])
        assert summary == ExactMatchSummary(passed=0, failed=0, not_applicable=0)


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
    for value in (-0.01, 1.01, True, "0.5"):
        with pytest.raises(ValueError):
            MetricScores(context_recall=value)


def test_accepts_exact_zero_and_one_metric_boundaries():
    assert MetricScores(faithfulness=0, answer_relevancy=1).faithfulness == 0
    assert AggregateMetrics(mean=0, median=1, min=0, max=1).max == 1


def test_report_rejects_unknown_case_identity_version():
    from evaluation.case_identity import CASE_IDENTITY_VERSION

    run = _make_run("baseline")
    run.case_identity_version = "unknown-case-schema"
    with pytest.raises(ValueError, match=CASE_IDENTITY_VERSION):
        compute_comparison(run, _make_run("current"))


async def test_case_identity_authority_advance_moves_serializer_runner_and_verifier(
    tmp_path, monkeypatch,
) -> None:
    """An authority change must advance every freshly produced comparison input."""
    import importlib
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import evaluation.case_identity as case_identity
    import evaluation.report as report_module
    import evaluation.runner as runner_module
    from evaluation.dataset import TestCase
    from plugins.expert.composition import expert_full_composition_fingerprint

    advanced = "evaluation-case-identity/v2"
    with monkeypatch.context() as patcher:
        patcher.setattr(case_identity, "CASE_IDENTITY_VERSION", advanced)
        report_module = importlib.reload(report_module)
        runner_module = importlib.reload(runner_module)
        invariant = "a" * 64

        async def run(mode: str, label: str):
            invoker = AsyncMock()
            invoker.composition_fingerprint = invariant
            invoker.evaluation_identity = SimpleNamespace(
                hierarchy_mode=mode,
                invariant_composition_fingerprint=invariant,
                full_composition_fingerprint=expert_full_composition_fingerprint(
                    invariant, mode,
                ),
            )
            invoker.invoke.return_value = ("answer", ["context"], [])
            scorer = AsyncMock()
            scorer.score.return_value = dict.fromkeys(
                ("faithfulness", "answer_relevancy", "context_precision", "context_recall"),
                0.5,
            )
            return await runner_module.EvaluationRunner(invoker, scorer, tmp_path).run(
                [TestCase(question="q", expected_answer="a", relevant_documents=["d"])],
                "expert", label=label, corpus_revision="r1",
            )

        flat = await run("flat", "flat")
        hierarchical = await run("hierarchical", "hierarchical")
        assert case_identity.evaluation_case_identity_payload({
            "question": "q", "expected_answer": "a", "relevant_documents": ["d"],
        })["schema"] == advanced
        persisted = report_module.load_comparison_run(
            next(tmp_path.glob("*flat.json")).read_text()
        )
        assert flat.case_identity_version == persisted.case_identity_version == advanced
        assert report_module.compute_comparison(flat, hierarchical).deltas

    importlib.reload(report_module)
    importlib.reload(runner_module)


def test_case_schema_extension_cannot_diverge_producer_and_verifier():
    from pydantic import BaseModel
    from evaluation.case_identity import evaluation_case_identity_payload

    class FutureCase(BaseModel):
        question: str
        expected_answer: str
        relevant_documents: list[str]
        required_future_field: str

    with pytest.raises(ValueError, match="schema"):
        evaluation_case_identity_payload(
            FutureCase(
                question="q",
                expected_answer="a",
                relevant_documents=["d"],
                required_future_field="x",
            )
        )


def test_v6_comparison_accepts_equivalent_default_representation():
    assert compute_comparison(_make_run("baseline"), _make_run("current")).deltas


def test_successful_metric_scores_require_exact_non_null_inventory():
    from evaluation.report import canonical_metric_scores

    with pytest.raises(ValueError):
        canonical_metric_scores(
            {
                "faithfulness": 0,
                "answer_relevancy": 0,
                "context_precision": 0,
                "context_recall": None,
            }
        )
    with pytest.raises(ValueError):
        canonical_metric_scores(
            {
                "faithfulness": 0,
                "answer_relevancy": 0,
                "context_precision": 0,
                "context_recall": 0,
                "extra": 0,
            }
        )


def test_canonical_metric_scores_maps_the_real_ragas_context_precision_column(caplog):
    """Regression guard for D-1: RAGAS 0.4.3 never publishes a column named
    ``context_precision`` — it publishes
    ``llm_context_precision_without_reference``. If ``METRIC_ALIASES`` stops
    mapping that published name to the stored ``context_precision`` field,
    this test must fail: a genuine RAGAS harvest would then always be
    missing the metric, exactly as it silently was before the fix.
    """
    from evaluation.report import canonical_metric_scores

    canonical = canonical_metric_scores(
        {
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "llm_context_precision_without_reference": 0.7,
            "context_recall": 0.6,
        }
    )
    assert canonical["context_precision"] == 0.7

    # FR-025: an unrecognised RAGAS column must be logged, not silently
    # dropped, so this class of naming drift cannot regress unnoticed again.
    caplog.clear()
    with caplog.at_level("WARNING", logger="evaluation.report"):
        with pytest.raises(ValueError):
            canonical_metric_scores(
                {
                    "faithfulness": 0.9,
                    "answer_relevancy": 0.8,
                    "some_future_ragas_rename": 0.7,
                    "context_recall": 0.6,
                }
            )
    assert any("some_future_ragas_rename" in record.message for record in caplog.records)


def test_metric_scores_clamp_one_ulp_float_error_at_the_unit_boundary():
    """RAGAS's un-clamped cosine-mean metrics legitimately return e.g.
    1.0000000000000007 for a well-answered case; that must not fail-close
    the whole case, but a real out-of-domain value still must."""
    from evaluation.report import canonical_metric_scores

    canonical = canonical_metric_scores(
        {
            "faithfulness": 1.0000000000000007,
            "answer_relevancy": -1e-16,
            "context_precision": 0.5,
            "context_recall": 1.0,
        }
    )
    assert canonical["faithfulness"] == 1.0
    assert canonical["answer_relevancy"] == 0.0

    with pytest.raises(ValueError):
        canonical_metric_scores(
            {
                "faithfulness": 1.0 + 1e-8,
                "answer_relevancy": 0,
                "context_precision": 0,
                "context_recall": 0,
            }
        )
    with pytest.raises(ValueError):
        canonical_metric_scores(
            {
                "faithfulness": 1.5,
                "answer_relevancy": 0,
                "context_precision": 0,
                "context_recall": 0,
            }
        )
    with pytest.raises(ValueError):
        canonical_metric_scores(
            {
                "faithfulness": float("nan"),
                "answer_relevancy": 0,
                "context_precision": 0,
                "context_recall": 0,
            }
        )


def test_comparison_rejects_provider_alias_or_incomplete_metric_inventory():
    baseline, current = _make_run("baseline"), _make_run("current")
    baseline.aggregate.pop("context_recall")
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_comparison_rejects_missing_case_identity_version():
    baseline, current = _make_run("baseline"), _make_run("current")
    baseline.case_identity_version = None
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_comparison_rejects_unknown_case_identity_version():
    baseline, current = _make_run("baseline"), _make_run("current")
    baseline.case_identity_version = "future/v2"
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_comparison_rejects_contradictory_case_identity_version():
    baseline, current = _make_run("baseline"), _make_run("current")
    current.case_identity_version = "evaluation-case-identity/v2"
    with pytest.raises(ValueError):
        compute_comparison(baseline, current)


def test_comparison_rejects_future_case_identity_fields(tmp_path, monkeypatch):
    """Comparison validates raw run and case objects before model normalization."""
    from click.testing import CliRunner
    from evaluation.cli import cli

    directory = tmp_path / "evaluations"
    directory.mkdir()
    baseline, current = _make_run("baseline"), _make_run("current")
    baseline_raw = baseline.model_dump()
    current_raw = current.model_dump()
    # The permissive historical display loader remains able to read this body.
    historical = baseline_raw | {"historical_display_note": "retained"}
    assert EvaluationRun.model_validate(historical).id == "baseline"

    for side, payload, field in (
        ("baseline", baseline_raw | {"future_run_identity": "x"}, "run"),
        ("current", current_raw | {"cases": [current_raw["cases"][0] | {"future_case_identity": "x"}]}, "case"),
    ):
        (directory / "baseline.json").write_text(__import__("json").dumps(baseline_raw))
        (directory / "current.json").write_text(__import__("json").dumps(current_raw))
        (directory / f"{side}.json").write_text(__import__("json").dumps(payload))
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(cli, ["compare", "baseline", "current"])
        assert result.exit_code != 0, field
        assert "unknown fields" in result.output


def test_comparison_rejects_unknown_raw_case_score_before_normalization():
    """The strict comparison loader sees score keys Pydantic would discard."""
    import json
    from evaluation.report import load_comparison_run

    baseline = _make_run("baseline")
    raw = baseline.model_dump()
    raw["cases"][0]["scores"]["undeclared_provider_score"] = 0.5

    # Historical display remains permissive; only comparison is strict.
    assert EvaluationRun.model_validate(raw).id == "baseline"
    with pytest.raises(ValueError, match="scores contain unknown fields"):
        load_comparison_run(json.dumps(raw))


@pytest.mark.parametrize(
    "mutation",
    [
        "plugin",
        "mode",
        "dataset",
        "bok",
        "corpus",
        "success",
        "invariant",
        "full",
        "failure",
        "legacy",
    ],
)
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


@pytest.mark.parametrize(
    "field, varied",
    [
        ("embeddings_query_max_utf8_bytes", 16384),
        ("query_rewrite_max_utf8_bytes", 2048),
        ("embeddings_max_attempts", 2),
        ("embeddings_attempt_timeout_seconds", 10),
        ("embeddings_total_deadline_seconds", 60),
    ],
)
def test_comparison_rejects_each_embedding_safety_control_mismatch(field, varied):
    from core.config import BaseConfig
    from plugins.expert.composition import (
        expert_composition_fingerprint,
        resolve_expert_composition,
    )

    def _invariant(**changes) -> str:
        config = BaseConfig(
            plugin_type="expert", llm_model="model-a",
            llm_base_url="http://local", **changes,
        )
        return expert_composition_fingerprint(
            resolve_expert_composition(config).authority
        )

    base_invariant = _invariant()
    varied_invariant = _invariant(**{field: varied})
    # Each safety control is part of the invariant composition identity.
    assert base_invariant != varied_invariant

    baseline, current = _make_run("baseline"), _make_run("current")
    baseline.invariant_composition_fingerprint = base_invariant
    baseline.full_composition_fingerprint = expert_full_composition_fingerprint(
        base_invariant, baseline.hierarchy_mode
    )
    current.invariant_composition_fingerprint = varied_invariant
    current.full_composition_fingerprint = expert_full_composition_fingerprint(
        varied_invariant, current.hierarchy_mode
    )
    with pytest.raises(ValueError, match="invariant_composition_fingerprint differs"):
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


_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_root_readme_documents_equal_invariant_and_distinct_full_fingerprints():
    text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(text.lower().split())
    assert "equal invariant fingerprints" in normalized
    assert "full fingerprints must be present, recomputable" in normalized
    assert "explicit modes, and different for flat versus hierarchical" in normalized
    assert "both full fingerprints equal" not in normalized


def test_expert_readme_documents_equal_invariant_and_distinct_full_fingerprints():
    text = (_REPO_ROOT / "plugins" / "expert" / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(text.lower().split())
    assert "invariant fingerprints are equal" in normalized
    assert (
        "both full fingerprints are present, recomputable from the invariant plus mode"
        in normalized
    )
    assert "different for flat versus hierarchical" in normalized
    assert "both full fingerprints equal" not in normalized


class TestFormatComparison:
    def test_contains_metric_deltas(self):
        report = ComparisonReport(
            baseline_id="baseline",
            current_id="current",
            deltas={
                "faithfulness": MetricDelta(
                    baseline=0.80,
                    current=0.90,
                    absolute_delta=0.10,
                    percentage_change=12.5,
                ),
            },
        )
        output = format_comparison(report)
        assert "baseline" in output
        assert "current" in output
        assert "faithfulness" in output
        assert "12.5%" in output

    def test_omits_exact_match_section_when_not_present(self):
        report = ComparisonReport(baseline_id="b", current_id="c", deltas={})
        output = format_comparison(report)
        assert "Exact-match assertions" not in output

    def test_renders_exact_match_delta_when_present(self):
        report = ComparisonReport(
            baseline_id="b",
            current_id="c",
            deltas={},
            exact_match=ExactMatchDelta(
                baseline_pass_rate=0.5,
                current_pass_rate=0.75,
                baseline_checked=4,
                baseline_not_applicable=1,
                current_checked=4,
                current_not_applicable=1,
            ),
        )
        output = format_comparison(report)
        assert "Exact-match assertions" in output
        assert "50.0%" in output
        assert "75.0%" in output
        assert "NOTE" not in output

    def test_flags_denominator_mismatch_between_runs(self):
        report = ComparisonReport(
            baseline_id="b",
            current_id="c",
            deltas={},
            exact_match=ExactMatchDelta(
                baseline_pass_rate=1.0,
                current_pass_rate=1.0,
                baseline_checked=2,
                baseline_not_applicable=3,
                current_checked=4,
                current_not_applicable=1,
            ),
        )
        output = format_comparison(report)
        assert "NOTE" in output
        assert "not a like-for-like comparison" in output

    def test_renders_na_when_a_side_has_no_checked_cases(self):
        report = ComparisonReport(
            baseline_id="b",
            current_id="c",
            deltas={},
            exact_match=ExactMatchDelta(
                baseline_pass_rate=None,
                current_pass_rate=1.0,
                baseline_checked=0,
                baseline_not_applicable=5,
                current_checked=2,
                current_not_applicable=0,
            ),
        )
        output = format_comparison(report)
        assert "N/A" in output


class TestComputeComparisonExactMatch:
    def test_comparison_includes_exact_match_delta_computed_from_both_runs(self):
        baseline = _make_run("baseline")
        baseline.cases[0].assertion_outcome = AssertionOutcome(status="passed", missing=[])
        current = _make_run("current")
        current.cases[0].assertion_outcome = AssertionOutcome(status="failed", missing=["x"])

        report = compute_comparison(baseline, current)

        assert report.exact_match is not None
        assert report.exact_match.baseline_pass_rate == 1.0
        assert report.exact_match.current_pass_rate == 0.0
        assert report.exact_match.baseline_checked == 1
        assert report.exact_match.current_checked == 1

    def test_comparison_exact_match_is_none_pass_rate_when_all_cases_unanchored(self):
        baseline = _make_run("baseline")
        current = _make_run("current")

        report = compute_comparison(baseline, current)

        assert report.exact_match is not None
        assert report.exact_match.baseline_pass_rate is None
        assert report.exact_match.current_pass_rate is None
        assert report.exact_match.baseline_not_applicable == 0
        assert report.exact_match.baseline_checked == 0
