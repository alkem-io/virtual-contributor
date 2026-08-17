"""Click-based CLI for the RAG evaluation framework."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import numbers
import sys
from pathlib import Path
from typing import cast

import click

from evaluation.dataset import load_test_set
from evaluation.report import (
    format_run_summary,
    compute_comparison,
    format_comparison,
    load_comparison_run,
)


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
def cli():
    """RAG Evaluation Framework for Alkemio Virtual Contributor."""
    _setup_logging()


@cli.command()
@click.option("--plugin", default="guidance", help="Plugin type to evaluate (guidance, expert)")
@click.option("--label", default=None, help="Optional label for the run")
@click.option(
    "--test-set",
    default="evaluation/golden/test_set.jsonl",
    type=click.Path(),
    help="Path to golden test set JSONL file",
)
@click.option(
    "--body-of-knowledge-id",
    default=None,
    help="Body of knowledge ID (for expert plugin)",
)
@click.option("--corpus-revision", default=None, help="Immutable operator corpus/re-ingestion revision (required for Expert)")
def run(plugin: str, label: str | None, test_set: str, body_of_knowledge_id: str | None, corpus_revision: str | None):
    """Run the evaluation suite against the pipeline."""
    plugin = plugin.lower().replace("-", "_")
    if plugin == "expert" and not corpus_revision:
        raise click.UsageError("Expert evaluation requires --corpus-revision")
    asyncio.run(_run_evaluation(plugin, label, Path(test_set), body_of_knowledge_id, corpus_revision))


async def _run_evaluation(
    plugin_type: str,
    label: str | None,
    test_set_path: Path,
    body_of_knowledge_id: str | None,
    corpus_revision: str | None,
) -> None:
    from core.config import BaseConfig
    from evaluation.metrics import create_metrics
    from evaluation.pipeline_invoker import PipelineInvoker
    from evaluation.runner import EvaluationRunner, Scorer

    # Load test set
    try:
        test_cases = load_test_set(test_set_path)
    except (FileNotFoundError, ValueError) as exc:
        click.echo(f"Error loading test set: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Loaded {len(test_cases)} test cases from {test_set_path}")

    # Initialize pipeline
    # The explicit CLI selection wins over blank, generic, or conflicting env.
    plugin_type = plugin_type.lower().replace("-", "_")
    config = BaseConfig(plugin_type=plugin_type)
    invoker = PipelineInvoker(
        plugin_type=plugin_type,
        config=config,
        body_of_knowledge_id=body_of_knowledge_id,
    )

    try:
        await invoker.setup()
    except Exception as exc:
        click.echo(f"Pipeline initialization failed: {exc}", err=True)
        try:
            await invoker.shutdown()
        except Exception:
            pass
        sys.exit(1)

    # Configure RAGAS metrics with pipeline's own LLM
    try:
        from langchain_openai import OpenAIEmbeddings

        embeddings = OpenAIEmbeddings(
            openai_api_key=config.embeddings_api_key,
            openai_api_base=config.embeddings_endpoint,
            model=config.embeddings_model_name or "text-embedding-3-small",
        )
        metrics = create_metrics(invoker.langchain_chat_model, embeddings)
    except Exception as exc:
        click.echo(f"Failed to configure evaluation metrics: {exc}", err=True)
        await invoker.shutdown()
        sys.exit(1)

    scorer = Scorer(metrics)
    runner = EvaluationRunner(
        pipeline_invoker=invoker,
        scorer=scorer,
    )

    try:
        evaluation_run = await runner.run(
            test_cases,
            plugin_type=plugin_type,
            label=label,
            test_set_path=str(test_set_path),
            body_of_knowledge_id=body_of_knowledge_id,
            corpus_revision=corpus_revision,
        )
        click.echo("")
        click.echo(format_run_summary(evaluation_run))
    finally:
        await invoker.shutdown()


@cli.command()
@click.argument("baseline_id")
@click.argument("current_id")
def compare(baseline_id: str, current_id: str):
    """Compare two evaluation runs by their IDs."""
    evaluations_dir = Path("evaluations")

    baseline_path = evaluations_dir / f"{baseline_id}.json"
    current_path = evaluations_dir / f"{current_id}.json"

    if not baseline_path.exists():
        click.echo(f"Baseline run not found: {baseline_path}", err=True)
        sys.exit(1)
    if not current_path.exists():
        click.echo(f"Current run not found: {current_path}", err=True)
        sys.exit(1)

    try:
        baseline = load_comparison_run(baseline_path.read_text())
        current = load_comparison_run(current_path.read_text())
    except (ValueError, OSError) as exc:
        click.echo(f"Failed to load run files: {exc}", err=True)
        sys.exit(1)

    report = compute_comparison(baseline, current)
    click.echo(format_comparison(report))


@cli.command("generate")
@click.option("--collection", required=True, help="ChromaDB collection name")
@click.option("--count", default=35, help="Number of test cases to generate")
@click.option(
    "--output",
    default="evaluation/golden/synthetic.jsonl",
    type=click.Path(),
    help="Output JSONL file",
)
def generate_cmd(collection: str, count: int, output: str):
    """Generate synthetic test cases from indexed content."""
    asyncio.run(_generate(collection, count, Path(output)))


async def _generate(collection: str, count: int, output: Path) -> None:
    from evaluation.generator import generate_synthetic_test_set

    await generate_synthetic_test_set(collection, count, output)


@cli.command("list")
def list_runs():
    """List previous evaluation runs."""
    evaluations_dir = Path("evaluations")

    if not evaluations_dir.exists():
        click.echo("No evaluations directory found.")
        return

    run_files = sorted(evaluations_dir.glob("*.json"), reverse=True)
    if not run_files:
        click.echo("No evaluation runs found.")
        return

    click.echo("Evaluation Runs:")
    header = f"  {'ID':<36}{'Plugin':<12}{'Cases':>6}{'State':<12}{'Faith.':>8}{'Relev.':>8}{'Prec.':>8}{'Recall':>8}"
    click.echo(header)

    for f in run_files:
        try:
            data = json.loads(f.read_text())
            run_id = str(data.get("id", f.stem))
            plugin = str(data.get("plugin_type", "?"))
            cases = data.get("test_case_count", "?")
            state, metrics = _list_run_state(data)
            click.echo(
                f"  {run_id:<36}{plugin:<12}{str(cases):>6}{state:<12}"
                f"{metrics[0]:>8}{metrics[1]:>8}{metrics[2]:>8}{metrics[3]:>8}"
            )
        except json.JSONDecodeError:
            click.echo(f"  {f.stem:<36}{'?':<12}{'?':>6}{'invalid':<12}{'N/A':>8}{'N/A':>8}{'N/A':>8}{'N/A':>8}")
        except Exception as exc:
            click.echo(f"  {f.stem:<36} — error reading: {exc}")

    click.echo(f"\n{len(run_files)} runs found in evaluations/")


def _list_run_state(data: object) -> tuple[str, tuple[str, str, str, str]]:
    """Classify display-only artifacts without inventing absent scores."""
    unavailable = ("N/A", "N/A", "N/A", "N/A")
    if not isinstance(data, dict):
        return "invalid", unavailable
    counts = (data.get("test_case_count"), data.get("success_count"), data.get("failure_count"))
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        return "invalid", unavailable
    total, successful, failed = cast(tuple[int, int, int], counts)
    if successful + failed != total:
        return "invalid", unavailable
    aggregate = data.get("aggregate")
    # Aggregate statistics are evidence from successful cases. A failed-only
    # run is useful inventory, but has no metric evidence to display.
    if successful == 0:
        if aggregate == {}:
            return "N/A", unavailable
        return "invalid", unavailable
    if not isinstance(aggregate, dict):
        return "invalid", unavailable
    names = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
    if set(aggregate) != set(names):
        return "incomplete", unavailable
    required_statistics = {"mean", "median", "min", "max"}
    values: list[str] = []
    for name in names:
        value = aggregate[name]
        if not isinstance(value, dict) or set(value) != required_statistics:
            return "incomplete", unavailable
        statistics = tuple(value[statistic] for statistic in ("mean", "median", "min", "max"))
        converted: list[float] = []
        for statistic in statistics:
            if isinstance(statistic, bool) or not isinstance(statistic, numbers.Real):
                return "invalid", unavailable
            try:
                numeric = float(statistic)
            except (OverflowError, TypeError, ValueError):
                return "invalid", unavailable
            if not math.isfinite(numeric) or not 0 <= numeric <= 1:
                return "invalid", unavailable
            converted.append(numeric)
        values.append(f"{converted[0]:.3f}")
    return "complete", tuple(values)  # type: ignore[return-value]
