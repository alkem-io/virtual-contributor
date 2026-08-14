"""Ingest engine span coverage."""

from core.domain.pipeline.engine import IngestEngine, PipelineContext
from core.tracing import shutdown_tracing


class AddChunkStep:
    name = "chunk"

    async def execute(self, context: PipelineContext) -> None:
        context.chunks.append(object())


async def test_ingest_step_spans_include_metrics(traced_exporter) -> None:
    engine = IngestEngine(steps=[AddChunkStep()])
    await engine.run([], "knowledge")
    shutdown_tracing()
    span = traced_exporter.get_finished_spans()[0]
    assert span.name == "vc.ingest.step chunk"
    assert span.attributes["vc.step.items_out"] == 1


async def test_erroring_step_emits_destructive_skip_span(traced_exporter) -> None:
    class FailingStep:
        name = "failing"

        async def execute(self, context: PipelineContext) -> None:
            raise RuntimeError("failed")

    class DestructiveStep:
        name = "cleanup"
        destructive = True

        async def execute(self, context: PipelineContext) -> None:
            raise AssertionError("must be skipped")

    await IngestEngine(steps=[FailingStep(), DestructiveStep()]).run([], "knowledge")
    shutdown_tracing()
    skipped = next(span for span in traced_exporter.get_finished_spans() if span.name == "vc.ingest.step cleanup")
    assert skipped.attributes["vc.step.skipped"] is True
    assert skipped.attributes["vc.step.skip_reason"] == "prior_errors"
