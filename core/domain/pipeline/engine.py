"""Pipeline engine: composable step-based ingestion framework."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from core.domain.ingest_pipeline import Chunk, Document, IngestResult

logger = logging.getLogger(__name__)


@runtime_checkable
class PipelineStep(Protocol):
    @property
    def name(self) -> str: ...

    async def execute(self, context: PipelineContext) -> None: ...


@dataclass
class StepMetrics:
    duration: float = 0.0
    items_in: int = 0
    items_out: int = 0
    error_count: int = 0


@dataclass
class PipelineContext:
    collection_name: str
    documents: list[Document]
    chunks: list[Chunk] = field(default_factory=list)
    document_summaries: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, StepMetrics] = field(default_factory=dict)
    chunks_stored: int = 0
    unchanged_chunk_hashes: set[str] = field(default_factory=set)
    orphan_ids: set[str] = field(default_factory=set)
    removed_document_ids: set[str] = field(default_factory=set)
    changed_document_ids: set[str] = field(default_factory=set)
    chunks_skipped: int = 0
    chunks_deleted: int = 0
    change_detection_ran: bool = False


class IngestEngine:
    """Execute an ordered list of PipelineStep instances."""

    def __init__(self, steps: list[PipelineStep]) -> None:
        self._steps = steps

    async def run(
        self,
        documents: list[Document],
        collection_name: str,
    ) -> IngestResult:
        context = PipelineContext(
            collection_name=collection_name,
            documents=documents,
        )

        for step in self._steps:
            items_before = len(context.chunks)
            errors_before = len(context.errors)

            # Gate: skip destructive steps when prior errors exist
            if getattr(step, "destructive", False) and context.errors:
                n_errors = len(context.errors)
                msg = (
                    f"{step.name}: skipped "
                    f"(destructive step gated by {n_errors} prior error(s))"
                )
                context.errors.append(msg)
                logger.warning(
                    "Skipping destructive step '%s' due to %d prior error(s)",
                    step.name,
                    n_errors,
                )
                context.metrics[step.name] = StepMetrics(
                    duration=0.0,
                    items_in=items_before,
                    items_out=len(context.chunks),
                    error_count=1,
                )
                continue

            start = time.monotonic()

            try:
                await step.execute(context)
            except Exception as exc:
                context.errors.append(f"{step.name}: {exc}")
                logger.exception("Step '%s' failed", step.name)

            elapsed = time.monotonic() - start
            context.metrics[step.name] = StepMetrics(
                duration=elapsed,
                items_in=items_before,
                items_out=len(context.chunks),
                error_count=len(context.errors) - errors_before,
            )

        return IngestResult(
            collection_name=collection_name,
            documents_processed=len(documents),
            chunks_stored=context.chunks_stored,
            errors=context.errors,
            success=len(context.errors) == 0,
            chunks_skipped=context.chunks_skipped,
            chunks_deleted=context.chunks_deleted,
        )
