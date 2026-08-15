"""Report formatting: aggregate summary tables and before/after comparison."""

from __future__ import annotations

import re
import hashlib
import json
import statistics

from plugins.expert.composition import expert_full_composition_fingerprint

from pydantic import BaseModel, Field


class SourceInfo(BaseModel):
    """Source metadata from pipeline response."""

    uri: str | None = None
    title: str | None = None
    score: float | None = None


class MetricScores(BaseModel):
    """Per-metric scores for a single evaluation case."""

    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None


class EvaluationCase(BaseModel):
    """A completed evaluation of a single test case."""

    index: int
    question: str
    expected_answer: str
    relevant_documents: list[str]
    pipeline_answer: str | None = None
    retrieved_contexts: list[str] = Field(default_factory=list)
    retrieved_sources: list[SourceInfo] = Field(default_factory=list)
    scores: MetricScores | None = None
    duration_seconds: float
    error: str | None = None


class AggregateMetrics(BaseModel):
    """Summary statistics for a single metric across all cases."""

    mean: float
    median: float
    min: float
    max: float


class EvaluationRun(BaseModel):
    """A complete evaluation run persisted as JSON."""

    id: str
    timestamp: str
    label: str | None = None
    plugin_type: str
    composition_fingerprint: str | None = None
    composition_identity_version: int | None = None
    # v4 pairing identity. Optional only so historical JSON remains displayable;
    # comparison below intentionally requires every member.
    hierarchy_mode: str | None = None
    test_set_digest: str | None = None
    body_of_knowledge_digest: str | None = None
    corpus_revision: str | None = None
    successful_case_digests: list[str] | None = None
    invariant_composition_fingerprint: str | None = None
    full_composition_fingerprint: str | None = None
    test_set_path: str
    test_case_count: int
    success_count: int
    failure_count: int
    duration_seconds: float
    aggregate: dict[str, AggregateMetrics]
    cases: list[EvaluationCase]


class MetricDelta(BaseModel):
    """Comparison between two runs for a single metric."""

    baseline: float
    current: float
    absolute_delta: float
    percentage_change: float


class ComparisonReport(BaseModel):
    """Before/after comparison between two evaluation runs."""

    baseline_id: str
    current_id: str
    deltas: dict[str, MetricDelta]


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


def format_run_summary(run: EvaluationRun, output_path: str | None = None) -> str:
    """Format a human-readable summary for a completed evaluation run."""
    duration_min = int(run.duration_seconds // 60)
    duration_sec = int(run.duration_seconds % 60)

    lines = [
        f"RAG Evaluation Run: {run.id}",
        f"Plugin: {run.plugin_type} | Test cases: {run.test_case_count} | Duration: {duration_min}m {duration_sec}s",
        "",
        "Results:",
        f"  {'Metric':<22}{'Mean':>8}{'Median':>8}{'Min':>8}{'Max':>8}",
    ]

    for name in METRIC_NAMES:
        if name in run.aggregate:
            agg = run.aggregate[name]
            lines.append(
                f"  {name:<22}{agg.mean:>8.3f}{agg.median:>8.3f}{agg.min:>8.3f}{agg.max:>8.3f}"
            )

    # Failures
    failures = [c for c in run.cases if c.error is not None]
    lines.append("")
    lines.append(f"Failures: {run.failure_count}/{run.test_case_count}")
    for c in failures:
        q_short = c.question[:40] + "..." if len(c.question) > 40 else c.question
        lines.append(f'  [{c.index}] "{q_short}" — {c.error}')

    lines.append("")
    saved_path = output_path or f"evaluations/{run.id}.json"
    lines.append(f"Results saved: {saved_path}")

    return "\n".join(lines)


def format_comparison(report: ComparisonReport) -> str:
    """Format a before/after comparison table."""
    lines = [
        f"Comparison: {report.baseline_id} vs {report.current_id}",
        "",
        f"{'Metric':<22}{'Baseline':>10}{'Current':>10}{'Delta':>10}{'Change':>10}",
    ]

    improved = 0
    regressed = 0
    total = 0

    for name in METRIC_NAMES:
        if name in report.deltas:
            d = report.deltas[name]
            total += 1
            sign = "+" if d.absolute_delta >= 0 else ""
            pct_sign = "+" if d.percentage_change >= 0 else ""
            lines.append(
                f"{name:<22}{d.baseline:>10.3f}{d.current:>10.3f}"
                f"{sign}{d.absolute_delta:>9.3f}{pct_sign}{d.percentage_change:>8.1f}%"
            )
            if d.absolute_delta > 0:
                improved += 1
            elif d.absolute_delta < 0:
                regressed += 1

    lines.append("")
    lines.append(f"Overall: {improved}/{total} metrics improved, {regressed}/{total} regressed")

    return "\n".join(lines)


def compute_comparison(
    baseline: EvaluationRun, current: EvaluationRun
) -> ComparisonReport:
    """Compute per-metric deltas between two runs."""
    runs = (baseline, current)
    required = (
        "hierarchy_mode", "test_set_digest", "body_of_knowledge_digest",
        "corpus_revision", "successful_case_digests",
        "invariant_composition_fingerprint", "full_composition_fingerprint",
    )
    if any(getattr(run, field) in (None, "") for run in runs for field in required):
        raise ValueError("Evaluation runs lack complete v5 pairing identity")
    if any(run.composition_identity_version != 5 for run in runs):
        raise ValueError("Evaluation runs require v5 composition identity")
    if baseline.plugin_type != "expert" or current.plugin_type != "expert":
        raise ValueError("Only Expert evaluation runs are comparable")
    if baseline.hierarchy_mode != "flat" or current.hierarchy_mode != "hierarchical":
        raise ValueError("Evaluation comparison requires Expert flat-to-hierarchical ordering")
    if baseline.failure_count or current.failure_count:
        raise ValueError("Evaluation comparison requires failure-free runs")
    for run in runs:
        _validate_persisted_run(run)
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}", run.corpus_revision or "") for run in runs):
        raise ValueError("Evaluation corpus revision is invalid")
    for field in ("test_set_digest", "body_of_knowledge_digest", "corpus_revision", "successful_case_digests", "invariant_composition_fingerprint"):
        if getattr(baseline, field) != getattr(current, field):
            raise ValueError(f"Evaluation {field} differs; comparison is not a paired experiment")
    if baseline.full_composition_fingerprint == current.full_composition_fingerprint:
        raise ValueError("Evaluation full fingerprints must differ by mode")
    for run in runs:
        expected = expert_full_composition_fingerprint(run.invariant_composition_fingerprint or "", run.hierarchy_mode or "")
        if run.full_composition_fingerprint != expected:
            raise ValueError("Evaluation full fingerprint is not bound to its mode")
    deltas: dict[str, MetricDelta] = {}

    for name in METRIC_NAMES:
        if name in baseline.aggregate and name in current.aggregate:
            b_mean = baseline.aggregate[name].mean
            c_mean = current.aggregate[name].mean
            abs_delta = c_mean - b_mean
            pct_change = (abs_delta / b_mean * 100) if b_mean != 0 else 0.0

            deltas[name] = MetricDelta(
                baseline=b_mean,
                current=c_mean,
                absolute_delta=abs_delta,
                percentage_change=pct_change,
            )

    return ComparisonReport(
        baseline_id=baseline.id,
        current_id=current.id,
        deltas=deltas,
    )


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _case_digest(case: EvaluationCase) -> str:
    """Return the canonical input identity for one persisted successful case."""
    payload = {
        "expected_answer": case.expected_answer,
        "question": case.question,
        "relevant_documents": case.relevant_documents,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_persisted_run(run: EvaluationRun) -> None:
    """Fail closed when persisted evidence is not a coherent v5 experiment."""
    if any(value < 0 for value in (run.test_case_count, run.success_count, run.failure_count)):
        raise ValueError("Evaluation counts must be nonnegative")
    if run.test_case_count != len(run.cases) or run.success_count + run.failure_count != run.test_case_count:
        raise ValueError("Evaluation case and count inventory is incoherent")
    if [case.index for case in run.cases] != list(range(run.test_case_count)):
        raise ValueError("Evaluation cases must be complete and ordered")
    if any(case.error is not None or case.scores is None or not case.pipeline_answer for case in run.cases):
        raise ValueError("Evaluation comparison requires complete successful cases")
    identities = [
        run.test_set_digest, run.body_of_knowledge_digest,
        run.invariant_composition_fingerprint, run.full_composition_fingerprint,
        *(run.successful_case_digests or []),
    ]
    if any(not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in identities):
        raise ValueError("Evaluation identities must be lowercase SHA-256 digests")
    digests = [_case_digest(case) for case in run.cases]
    if run.successful_case_digests != digests:
        raise ValueError("Evaluation successful case digests do not match cases")
    dataset_payload = [
        {"expected_answer": case.expected_answer, "question": case.question, "relevant_documents": case.relevant_documents}
        for case in run.cases
    ]
    expected_dataset = hashlib.sha256(
        json.dumps(dataset_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if run.test_set_digest != expected_dataset:
        raise ValueError("Evaluation test-set digest does not match cases")
    if set(run.aggregate) != set(METRIC_NAMES):
        raise ValueError("Evaluation aggregate metrics must include exactly the required metrics")
    for metric in METRIC_NAMES:
        if any(getattr(case.scores, metric) is None for case in run.cases):
            raise ValueError("Evaluation cases must include every required metric score")
        values = [getattr(case.scores, metric) for case in run.cases if getattr(case.scores, metric) is not None]
        aggregate = run.aggregate.get(metric)
        if not values or aggregate is None or aggregate.mean != statistics.mean(values) or aggregate.median != statistics.median(values) or aggregate.min != min(values) or aggregate.max != max(values):
            raise ValueError("Evaluation aggregate metrics do not match cases")
