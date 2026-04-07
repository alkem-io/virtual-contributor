"""Evaluation runner: orchestrates test case execution, scoring, and persistence."""

from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation.dataset import TestCase
from evaluation.report import (
    AggregateMetrics,
    EvaluationCase,
    EvaluationRun,
    MetricScores,
    SourceInfo,
)

logger = logging.getLogger(__name__)

METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


class Scorer:
    """Wraps RAGAS evaluation for single-case scoring."""

    def __init__(self, metrics: list) -> None:
        self._metrics = metrics

    async def score(
        self,
        question: str,
        answer: str,
        expected_answer: str,
        retrieved_contexts: list[str],
    ) -> dict[str, float]:
        """Score a single evaluation case using RAGAS metrics.

        Returns dict mapping metric name to float score.
        """
        from ragas import evaluate, EvaluationDataset, SingleTurnSample

        sample = SingleTurnSample(
            user_input=question,
            response=answer,
            reference=expected_answer,
            retrieved_contexts=retrieved_contexts if retrieved_contexts else [""],
        )
        dataset = EvaluationDataset(samples=[sample])

        result = evaluate(dataset=dataset, metrics=self._metrics)
        df = result.to_pandas()

        scores: dict[str, float] = {}
        for name in METRIC_NAMES:
            if name in df.columns:
                val = df[name].iloc[0]
                scores[name] = float(val) if val is not None else 0.0

        return scores


class EvaluationRunner:
    """Orchestrates evaluation: invokes pipeline, scores, persists results."""

    def __init__(
        self,
        pipeline_invoker,
        scorer,
        output_dir: Path = Path("evaluations"),
    ) -> None:
        self._invoker = pipeline_invoker
        self._scorer = scorer
        self._output_dir = output_dir

    async def run(
        self,
        test_cases: list[TestCase],
        plugin_type: str,
        label: str | None = None,
        test_set_path: str = "evaluation/golden/test_set.jsonl",
    ) -> EvaluationRun:
        """Execute the full evaluation suite.

        Processes each test case sequentially, capturing responses and scores.
        Failed cases are recorded but do not stop the run (FR-010).
        """
        run_start = time.monotonic()
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%dT%H%M%S")
        run_id = f"{ts_str}_{label}" if label else ts_str

        cases: list[EvaluationCase] = []
        success_count = 0
        failure_count = 0

        total = len(test_cases)
        for idx, tc in enumerate(test_cases):
            q_short = tc.question[:50] + "..." if len(tc.question) > 50 else tc.question
            logger.info("[%d/%d] Evaluating: \"%s\"", idx + 1, total, q_short)

            case_start = time.monotonic()
            try:
                # Invoke pipeline
                answer, contexts, sources_meta = await self._invoker.invoke(tc.question)

                # Score with RAGAS
                scores_dict = await self._scorer.score(
                    question=tc.question,
                    answer=answer,
                    expected_answer=tc.expected_answer,
                    retrieved_contexts=contexts,
                )

                case_duration = time.monotonic() - case_start
                logger.info("[%d/%d] done (%.1fs)", idx + 1, total, case_duration)

                sources = [
                    SourceInfo(uri=s.get("uri"), title=s.get("title"), score=s.get("score"))
                    for s in sources_meta
                ]

                cases.append(EvaluationCase(
                    index=idx,
                    question=tc.question,
                    expected_answer=tc.expected_answer,
                    relevant_documents=tc.relevant_documents,
                    pipeline_answer=answer,
                    retrieved_contexts=contexts,
                    retrieved_sources=sources,
                    scores=MetricScores(**scores_dict),
                    duration_seconds=case_duration,
                ))
                success_count += 1

            except Exception as exc:
                case_duration = time.monotonic() - case_start
                logger.warning(
                    "[%d/%d] FAILED (%.1fs): %s", idx + 1, total, case_duration, exc
                )
                cases.append(EvaluationCase(
                    index=idx,
                    question=tc.question,
                    expected_answer=tc.expected_answer,
                    relevant_documents=tc.relevant_documents,
                    error=str(exc),
                    duration_seconds=case_duration,
                ))
                failure_count += 1

        total_duration = time.monotonic() - run_start
        aggregate = self._compute_aggregate(cases)

        run = EvaluationRun(
            id=run_id,
            timestamp=ts.isoformat(),
            label=label,
            plugin_type=plugin_type,
            test_set_path=test_set_path,
            test_case_count=total,
            success_count=success_count,
            failure_count=failure_count,
            duration_seconds=total_duration,
            aggregate=aggregate,
            cases=cases,
        )

        self._persist(run)
        return run

    def _compute_aggregate(
        self, cases: list[EvaluationCase]
    ) -> dict[str, AggregateMetrics]:
        """Compute per-metric aggregate statistics from successful cases."""
        scored_cases = [c for c in cases if c.scores is not None]
        if not scored_cases:
            return {}

        aggregate: dict[str, AggregateMetrics] = {}
        for name in METRIC_NAMES:
            values = [
                getattr(c.scores, name)
                for c in scored_cases
                if c.scores is not None and getattr(c.scores, name) is not None
            ]
            if values:
                aggregate[name] = AggregateMetrics(
                    mean=statistics.mean(values),
                    median=statistics.median(values),
                    min=min(values),
                    max=max(values),
                )

        return aggregate

    def _persist(self, run: EvaluationRun) -> None:
        """Write evaluation run to JSON file."""
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"{run.id}.json"
        path.write_text(
            json.dumps(run.model_dump(), indent=2, default=str)
        )
        logger.info("Results saved: %s", path)
