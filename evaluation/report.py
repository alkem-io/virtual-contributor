"""Report formatting: aggregate summary tables and before/after comparison."""

from __future__ import annotations

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


def format_run_summary(run: EvaluationRun) -> str:
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
    lines.append(f"Results saved: evaluations/{run.id}.json")

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
