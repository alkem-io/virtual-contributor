"""Tests for evaluation/runner.py — orchestration, failure continuation, aggregate computation."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


def _expert_identity() -> SimpleNamespace:
    from plugins.expert.composition import expert_full_composition_fingerprint

    invariant = "a" * 64
    return SimpleNamespace(
        hierarchy_mode="flat",
        invariant_composition_fingerprint=invariant,
        full_composition_fingerprint=expert_full_composition_fingerprint(
            invariant, "flat"
        ),
    )


class _Result:
    def __init__(self, scores):
        self.scores = scores

    def to_pandas(self):
        raise AssertionError("Scorer must use RAGAS score records, not combined pandas rows")


def _install_ragas_result(monkeypatch, result) -> None:
    """Install the minimal real RAGAS 0.4.3 result seam used by Scorer."""
    class Dataset:
        def __init__(self, *, samples):
            self.samples = samples

    class Sample:
        def __init__(self, **kwargs):
            self.values = kwargs

    def evaluate(**kwargs):
        assert isinstance(kwargs["dataset"], Dataset)
        return result

    monkeypatch.setitem(sys.modules, "ragas", SimpleNamespace(
        evaluate=evaluate, EvaluationDataset=Dataset, SingleTurnSample=Sample,
    ))


async def test_scorer_maps_real_ragas_metric_names_to_exact_required_inventory(
    monkeypatch,
    tmp_path,
) -> None:
    from evaluation.runner import EvaluationRunner, Scorer

    class Result:
        scores = [{
            "faithfulness": 0,
            "answer_relevancy": 1,
            "llm_context_precision_without_reference": 0.5,
            "context_recall": 0.5,
        }]

        def to_pandas(self):
            raise AssertionError("combined dataset frame must not be read as metrics")

    _install_ragas_result(monkeypatch, Result())
    scorer = Scorer([])
    assert (await scorer.score("q", "a", "expected", ["context"]))["context_precision"] == 0.5

    invoker = AsyncMock()
    invoker.invoke.return_value = ("a", ["context"], [])
    run = await EvaluationRunner(invoker, scorer, tmp_path).run(_make_test_cases(1), "guidance")
    assert run.success_count == 1 and (tmp_path / f"{run.id}.json").exists()


async def test_scorer_rejects_missing_required_metric_without_none_coercion(monkeypatch) -> None:
    from evaluation.runner import Scorer

    with pytest.raises(ValueError):
        _install_ragas_result(monkeypatch, _Result([{"faithfulness": 0.1}]))
        await Scorer([]).score("q", "a", "expected", [])
    with pytest.raises(ValueError):
        _install_ragas_result(monkeypatch, _Result([]))
        await Scorer([]).score("q", "a", "expected", [])
    with pytest.raises(ValueError):
        _install_ragas_result(monkeypatch, _Result([{}, {}]))
        await Scorer([]).score("q", "a", "expected", [])


async def test_scorer_rejects_null_required_metric_without_zero_coercion(monkeypatch) -> None:
    from evaluation.runner import Scorer

    with pytest.raises(ValueError):
        _install_ragas_result(monkeypatch, _Result([{
                "faithfulness": 0.1,
                "answer_relevancy": 0.1,
                "llm_context_precision_without_reference": None,
                "context_recall": 0.1,
        }]))
        await Scorer([]).score("q", "a", "expected", [])
    with pytest.raises(ValueError):
        _install_ragas_result(monkeypatch, _Result([{
            "faithfulness": 0.1, "answer_relevancy": 0.1,
            "llm_context_precision_without_reference": 0.1, "context_recall": 0.1,
            "dataset_question": "q",
        }]))
        await Scorer([]).score("q", "a", "expected", [])


async def test_runner_does_not_persist_incomplete_metric_case_as_success(
    tmp_path,
) -> None:
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.invoke.return_value = ("answer", [], [])
    scorer = AsyncMock()
    scorer.score.return_value = {"faithfulness": 0.1}
    run = await EvaluationRunner(invoker, scorer, tmp_path).run(
        _make_test_cases(1), "guidance"
    )
    assert run.success_count == 0 and run.failure_count == 1


async def test_runner_persists_explicit_case_identity_version(tmp_path) -> None:
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.invoke.return_value = ("answer", [], [])
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = _expert_identity()
    scorer = AsyncMock()
    scorer.score.return_value = {
        "faithfulness": 0.1,
        "answer_relevancy": 0.1,
        "context_precision": 0.1,
        "context_recall": 0.1,
    }
    run = await EvaluationRunner(invoker, scorer, tmp_path).run(
        _make_test_cases(1), "expert", corpus_revision="r1"
    )
    assert run.case_identity_version == "evaluation-case-identity/v1"


async def test_expert_identity_missing_fails_before_invocation_or_scoring(
    tmp_path,
) -> None:
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = None
    scorer = AsyncMock()
    with pytest.raises(ValueError):
        await EvaluationRunner(invoker, scorer, tmp_path).run(
            _make_test_cases(1), "expert", corpus_revision="r1"
        )
    invoker.invoke.assert_not_awaited()
    scorer.score.assert_not_awaited()


async def test_expert_identity_incomplete_fails_before_invocation_or_scoring(tmp_path):
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = SimpleNamespace()
    scorer = AsyncMock()
    with pytest.raises(ValueError):
        await EvaluationRunner(invoker, scorer, tmp_path).run(
            _make_test_cases(1), "expert", corpus_revision="r1"
        )


async def test_expert_identity_invalid_mode_fails_before_invocation_or_scoring(
    tmp_path,
):
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = SimpleNamespace(
        hierarchy_mode="bad",
        invariant_composition_fingerprint="a" * 64,
        full_composition_fingerprint="a" * 64,
    )
    with pytest.raises(ValueError):
        await EvaluationRunner(invoker, AsyncMock(), tmp_path).run(
            _make_test_cases(1), "expert", corpus_revision="r1"
        )


async def test_expert_identity_full_binding_mismatch_fails_before_invocation_or_scoring(
    tmp_path,
):
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = SimpleNamespace(
        hierarchy_mode="flat",
        invariant_composition_fingerprint="a" * 64,
        full_composition_fingerprint="b" * 64,
    )
    with pytest.raises(ValueError):
        await EvaluationRunner(invoker, AsyncMock(), tmp_path).run(
            _make_test_cases(1), "expert", corpus_revision="r1"
        )


async def test_expert_identity_invariant_mismatch_fails_before_invocation_or_scoring(
    tmp_path,
):
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = SimpleNamespace(
        hierarchy_mode="flat",
        invariant_composition_fingerprint="b" * 64,
        full_composition_fingerprint="a" * 64,
    )
    with pytest.raises(ValueError):
        await EvaluationRunner(invoker, AsyncMock(), tmp_path).run(
            _make_test_cases(1), "expert", corpus_revision="r1"
        )


async def test_expert_identity_is_snapshotted_once_before_case_loop(tmp_path):
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.composition_fingerprint = "a" * 64
    invoker.evaluation_identity = _expert_identity()
    invoker.invoke.return_value = ("answer", [], [])
    scorer = AsyncMock()
    scorer.score.return_value = {
        "faithfulness": 0.1,
        "answer_relevancy": 0.1,
        "context_precision": 0.1,
        "context_recall": 0.1,
    }
    run = await EvaluationRunner(invoker, scorer, tmp_path).run(
        _make_test_cases(1), "expert", corpus_revision="r1"
    )
    assert run.invariant_composition_fingerprint == "a" * 64


async def test_guidance_runner_does_not_require_expert_identity_before_scoring(
    tmp_path,
):
    from evaluation.runner import EvaluationRunner

    invoker = AsyncMock()
    invoker.invoke.return_value = ("answer", [], [])
    scorer = AsyncMock()
    scorer.score.return_value = {
        "faithfulness": 0.1,
        "answer_relevancy": 0.1,
        "context_precision": 0.1,
        "context_recall": 0.1,
    }
    assert (
        await EvaluationRunner(invoker, scorer, tmp_path).run(
            _make_test_cases(1), "guidance"
        )
    ).success_count == 1


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

    async def test_runs_all_test_cases(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
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

    async def test_continues_on_failure(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
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

    async def test_runner_persists_complete_v4_pairing_identity(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from evaluation.runner import EvaluationRunner

        mock_pipeline_invoker.composition_fingerprint = "a" * 64
        from plugins.expert.composition import expert_full_composition_fingerprint

        mock_pipeline_invoker.evaluation_identity = SimpleNamespace(
            hierarchy_mode="flat",
            invariant_composition_fingerprint="a" * 64,
            full_composition_fingerprint=expert_full_composition_fingerprint(
                "a" * 64, "flat"
            ),
        )
        run = await EvaluationRunner(mock_pipeline_invoker, mock_scorer, tmp_path).run(
            _make_test_cases(1),
            plugin_type="expert",
            body_of_knowledge_id="bok",
            corpus_revision="reingest-1",
        )
        assert (
            run.test_set_digest
            and run.body_of_knowledge_digest
            and run.successful_case_digests
        )

    async def test_runner_persists_ordered_successful_case_digests(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from evaluation.runner import EvaluationRunner

        mock_pipeline_invoker.composition_fingerprint = "a" * 64
        from plugins.expert.composition import expert_full_composition_fingerprint

        mock_pipeline_invoker.evaluation_identity = SimpleNamespace(
            hierarchy_mode="flat",
            invariant_composition_fingerprint="a" * 64,
            full_composition_fingerprint=expert_full_composition_fingerprint(
                "a" * 64, "flat"
            ),
        )
        run = await EvaluationRunner(mock_pipeline_invoker, mock_scorer, tmp_path).run(
            _make_test_cases(2),
            plugin_type="expert",
            corpus_revision="reingest-1",
        )
        assert len(run.successful_case_digests or []) == 2

    async def test_persists_results_json(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from evaluation.runner import EvaluationRunner

        cases = _make_test_cases(2)
        runner = EvaluationRunner(
            pipeline_invoker=mock_pipeline_invoker,
            scorer=mock_scorer,
            output_dir=tmp_path,
        )
        await runner.run(cases, plugin_type="guidance", label="baseline")

        result_files = list(tmp_path.glob("*.json"))
        assert len(result_files) == 1
        data = json.loads(result_files[0].read_text())
        assert data["plugin_type"] == "guidance"
        assert data["label"] == "baseline"
        assert len(data["cases"]) == 2

    async def test_aggregate_computation(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from evaluation.runner import EvaluationRunner

        # Return different scores for different cases
        mock_scorer.score.side_effect = [
            {
                "faithfulness": 0.6,
                "answer_relevancy": 0.5,
                "context_precision": 0.4,
                "context_recall": 0.3,
            },
            {
                "faithfulness": 0.8,
                "answer_relevancy": 0.7,
                "context_precision": 0.6,
                "context_recall": 0.5,
            },
            {
                "faithfulness": 1.0,
                "answer_relevancy": 0.9,
                "context_precision": 0.8,
                "context_recall": 0.7,
            },
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

    async def test_empty_retrieval_still_scored(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
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

    async def test_judge_unreachable_records_error(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
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

    async def test_runner_rejects_invalid_metric_domain_before_persisting(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from evaluation.runner import EvaluationRunner

        mock_scorer.score.return_value = {"faithfulness": float("inf")}
        run = await EvaluationRunner(mock_pipeline_invoker, mock_scorer, tmp_path).run(
            _make_test_cases(1), plugin_type="guidance"
        )
        assert run.failure_count == 1

    async def test_runner_uses_public_identity_without_private_config(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from types import SimpleNamespace
        from evaluation.runner import EvaluationRunner
        from plugins.expert.composition import expert_full_composition_fingerprint

        invariant = "a" * 64
        mock_pipeline_invoker.composition_fingerprint = invariant
        mock_pipeline_invoker.evaluation_identity = SimpleNamespace(
            hierarchy_mode="flat",
            invariant_composition_fingerprint=invariant,
            full_composition_fingerprint=expert_full_composition_fingerprint(
                invariant, "flat"
            ),
        )
        run = await EvaluationRunner(mock_pipeline_invoker, mock_scorer, tmp_path).run(
            _make_test_cases(1), plugin_type="expert", corpus_revision="r1"
        )
        assert run.hierarchy_mode == "flat"

    async def test_runner_rejects_missing_or_contradictory_expert_identity(
        self, mock_pipeline_invoker, mock_scorer, tmp_path
    ):
        from evaluation.runner import EvaluationRunner

        with pytest.raises(ValueError, match="identity"):
            await EvaluationRunner(mock_pipeline_invoker, mock_scorer, tmp_path).run(
                _make_test_cases(1), plugin_type="expert", corpus_revision="r1"
            )
