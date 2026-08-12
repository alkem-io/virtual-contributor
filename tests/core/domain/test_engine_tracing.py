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
