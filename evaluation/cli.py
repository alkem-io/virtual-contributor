"""Click-based CLI for the RAG evaluation framework."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click

from evaluation.dataset import load_test_set
from evaluation.report import (
    EvaluationRun,
    format_run_summary,
    compute_comparison,
    format_comparison,
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
def run(plugin: str, label: str | None, test_set: str, body_of_knowledge_id: str | None):
    """Run the evaluation suite against the pipeline."""
    asyncio.run(_run_evaluation(plugin, label, Path(test_set), body_of_knowledge_id))


async def _run_evaluation(
    plugin_type: str,
    label: str | None,
    test_set_path: Path,
    body_of_knowledge_id: str | None,
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
    config = BaseConfig()
    invoker = PipelineInvoker(
        plugin_type=plugin_type,
        config=config,
        body_of_knowledge_id=body_of_knowledge_id,
    )

    try:
        await invoker.setup()
    except Exception as exc:
        click.echo(f"Pipeline initialization failed: {exc}", err=True)
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

    baseline = EvaluationRun.model_validate_json(baseline_path.read_text())
    current = EvaluationRun.model_validate_json(current_path.read_text())

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
    header = f"  {'ID':<36}{'Plugin':<12}{'Cases':>6}{'Faith.':>8}{'Relev.':>8}{'Prec.':>8}{'Recall':>8}"
    click.echo(header)

    for f in run_files:
        try:
            data = json.loads(f.read_text())
            run_id = data.get("id", f.stem)
            plugin = data.get("plugin_type", "?")
            cases = data.get("test_case_count", 0)
            agg = data.get("aggregate", {})

            faith = agg.get("faithfulness", {}).get("mean", 0)
            relev = agg.get("answer_relevancy", {}).get("mean", 0)
            prec = agg.get("context_precision", {}).get("mean", 0)
            recall = agg.get("context_recall", {}).get("mean", 0)

            click.echo(
                f"  {run_id:<36}{plugin:<12}{cases:>6}{faith:>8.3f}{relev:>8.3f}{prec:>8.3f}{recall:>8.3f}"
            )
        except (json.JSONDecodeError, Exception) as exc:
            click.echo(f"  {f.stem:<36} — error reading: {exc}")

    click.echo(f"\n{len(run_files)} runs found in evaluations/")
