"""Evaluation runner: orchestrates test case execution, scoring, and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from evaluation.dataset import TestCase, canonical_test_set_digest, successful_case_digest
from evaluation.report import (
    AggregateMetrics,
    EvaluationCase,
    EvaluationRun,
    MetricScores,
    SourceInfo,
    canonical_metric_scores,
)

logger = logging.getLogger(__name__)

METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


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

        result = await asyncio.to_thread(evaluate, dataset=dataset, metrics=self._metrics)
        df = result.to_pandas()

        return canonical_metric_scores({str(name): df[name].iloc[0] for name in df.columns})


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
        body_of_knowledge_id: str | None = None,
        corpus_revision: str | None = None,
    ) -> EvaluationRun:
        """Execute the full evaluation suite.

        Processes each test case sequentially, capturing responses and scores.
        Failed cases are recorded but do not stop the run (FR-010).
        """
        normalized_plugin = plugin_type.lower().replace("-", "_")
        if normalized_plugin == "expert" and (
            not isinstance(corpus_revision, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}", corpus_revision) is None
        ):
            raise ValueError("Expert evaluation requires a safe corpus revision")
        # The public identity is a pre-egress gate.  Snapshot validated
        # primitives now; never reread a mutable invoker after case work.
        if normalized_plugin == "expert":
            identity = getattr(self._invoker, "evaluation_identity", None)
            fingerprint = getattr(self._invoker, "composition_fingerprint", None)
            mode = getattr(identity, "hierarchy_mode", None)
            invariant = getattr(identity, "invariant_composition_fingerprint", None)
            full = getattr(identity, "full_composition_fingerprint", None)
            from plugins.expert.composition import expert_full_composition_fingerprint
            if (
                mode not in {"flat", "hierarchical"}
                or not isinstance(invariant, str)
                or not isinstance(full, str)
                or fingerprint != invariant
                or full != expert_full_composition_fingerprint(invariant, mode)
            ):
                raise ValueError("Expert evaluation identity is incomplete or contradictory")
        else:
            fingerprint = mode = invariant = full = None
        run_start = time.monotonic()
        ts = datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y%m%dT%H%M%S")
        safe_label = (
            re.sub(r"[^A-Za-z0-9._-]+", "-", label).strip("-")
            if label
            else ""
        )
        run_id = f"{ts_str}_{safe_label}" if safe_label else ts_str

        cases: list[EvaluationCase] = []
        success_count = 0
        failure_count = 0

        total = len(test_cases)
        for idx, tc in enumerate(test_cases):
            q_short = tc.question[:50] + "..." if len(tc.question) > 50 else tc.question
            logger.info("[%d/%d] Evaluating: \"%s\"", idx + 1, total, q_short)

            case_start = time.monotonic()
            answer: str | None = None
            contexts: list[str] = []
            sources_meta: list[dict] = []

            try:
                answer, contexts, sources_meta = await self._invoker.invoke(tc.question)
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
                continue

            try:
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
                    "[%d/%d] scoring FAILED (%.1fs): %s", idx + 1, total, case_duration, exc
                )
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
            composition_fingerprint=fingerprint,
            composition_identity_version=7 if normalized_plugin == "expert" else None,
            case_identity_version="evaluation-case-identity/v1" if normalized_plugin == "expert" else None,
            hierarchy_mode=mode,
            test_set_digest=canonical_test_set_digest(test_cases) if normalized_plugin == "expert" else None,
            body_of_knowledge_digest=hashlib.sha256((body_of_knowledge_id or "").encode("utf-8")).hexdigest() if normalized_plugin == "expert" else None,
            corpus_revision=corpus_revision if normalized_plugin == "expert" else None,
            successful_case_digests=[successful_case_digest(test_cases[c.index]) for c in cases if c.error is None] if normalized_plugin == "expert" else None,
            invariant_composition_fingerprint=invariant,
            full_composition_fingerprint=full,
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
