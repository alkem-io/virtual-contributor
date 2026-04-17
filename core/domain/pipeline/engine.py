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
    all_document_ids: set[str] = field(default_factory=set)
    raw_chunks_by_doc: dict[str, list[str]] = field(default_factory=dict)


class IngestEngine:
    """Execute an ordered list of PipelineStep instances.

    Supports two modes:

    * **Sequential** (backward-compatible): ``IngestEngine(steps=[...])``
      runs all steps on the full document set in one pass.

    * **Batched**: ``IngestEngine(batch_steps=[...], finalize_steps=[...],
      batch_size=5)`` partitions documents into batches, runs
      ``batch_steps`` per batch (persisting each), then runs
      ``finalize_steps`` once on accumulated results.
    """

    def __init__(
        self,
        steps: list[PipelineStep] | None = None,
        *,
        batch_steps: list[PipelineStep] | None = None,
        finalize_steps: list[PipelineStep] | None = None,
        batch_size: int = 5,
    ) -> None:
        if steps is not None and batch_steps is not None:
            raise ValueError("Cannot specify both 'steps' and 'batch_steps'")
        if steps is None and batch_steps is None:
            raise ValueError("Must specify either 'steps' or 'batch_steps'")
        if batch_steps is not None and finalize_steps is None:
            raise ValueError("'finalize_steps' is required when using 'batch_steps'")
        if steps is not None and finalize_steps is not None:
            raise ValueError("'finalize_steps' cannot be used with 'steps' (sequential mode)")

        self._steps = steps
        self._batch_steps = batch_steps
        self._finalize_steps = finalize_steps
        self._batch_size = max(1, batch_size)

    async def run(
        self,
        documents: list[Document],
        collection_name: str,
    ) -> IngestResult:
        if self._batch_steps is not None:
            return await self._run_batched(documents, collection_name)
        return await self._run_sequential(documents, collection_name)

    # ------------------------------------------------------------------
    # Sequential mode (backward-compatible)
    # ------------------------------------------------------------------

    async def _run_sequential(
        self,
        documents: list[Document],
        collection_name: str,
    ) -> IngestResult:
        assert self._steps is not None
        context = PipelineContext(
            collection_name=collection_name,
            documents=documents,
            all_document_ids={d.metadata.document_id for d in documents},
        )
        await self._run_steps(self._steps, context)
        return self._build_result(context, len(documents))

    # ------------------------------------------------------------------
    # Batched mode
    # ------------------------------------------------------------------

    async def _run_batched(
        self,
        documents: list[Document],
        collection_name: str,
    ) -> IngestResult:
        assert self._batch_steps is not None
        assert self._finalize_steps is not None

        all_document_ids = {d.metadata.document_id for d in documents}

        # Accumulators for cross-batch state
        global_document_summaries: dict[str, str] = {}
        global_orphan_ids: set[str] = set()
        global_removed_document_ids: set[str] = set()
        global_changed_document_ids: set[str] = set()
        global_unchanged_chunk_hashes: set[str] = set()
        global_errors: list[str] = []
        global_metrics: dict[str, StepMetrics] = {}
        global_raw_chunks_by_doc: dict[str, list[str]] = {}
        global_chunks_stored = 0
        global_chunks_skipped = 0
        global_change_detection_ran = False

        # Partition documents into batches
        for batch_idx in range(0, max(1, len(documents)), self._batch_size):
            batch_docs = documents[batch_idx : batch_idx + self._batch_size]
            if not batch_docs:
                continue

            batch_num = batch_idx // self._batch_size

            batch_ctx = PipelineContext(
                collection_name=collection_name,
                documents=batch_docs,
                all_document_ids=all_document_ids,
            )

            logger.info(
                "Running batch %d (%d documents) for collection %s",
                batch_num, len(batch_docs), collection_name,
            )

            await self._run_steps(
                self._batch_steps, batch_ctx, metrics_suffix=f"_batch_{batch_num}",
            )

            # Accumulate raw chunk content for BoK (before discarding chunks)
            for chunk in batch_ctx.chunks:
                if chunk.metadata.embedding_type == "chunk":
                    global_raw_chunks_by_doc.setdefault(
                        chunk.metadata.document_id, [],
                    ).append(chunk.content)

            # Merge batch results into global state
            global_document_summaries.update(batch_ctx.document_summaries)
            global_orphan_ids |= batch_ctx.orphan_ids
            global_removed_document_ids |= batch_ctx.removed_document_ids
            global_changed_document_ids |= batch_ctx.changed_document_ids
            global_unchanged_chunk_hashes |= batch_ctx.unchanged_chunk_hashes
            global_errors.extend(batch_ctx.errors)
            global_metrics.update(batch_ctx.metrics)
            global_chunks_stored += batch_ctx.chunks_stored
            global_chunks_skipped += batch_ctx.chunks_skipped
            if batch_ctx.change_detection_ran:
                global_change_detection_ran = True

        # Build finalize context — chunks starts empty; finalize steps
        # (e.g. BoK) append their own chunks for embedding/storing.
        finalize_ctx = PipelineContext(
            collection_name=collection_name,
            documents=documents,
            document_summaries=global_document_summaries,
            orphan_ids=global_orphan_ids,
            removed_document_ids=global_removed_document_ids,
            changed_document_ids=global_changed_document_ids,
            unchanged_chunk_hashes=global_unchanged_chunk_hashes,
            errors=global_errors,
            metrics=global_metrics,
            chunks_stored=global_chunks_stored,
            chunks_skipped=global_chunks_skipped,
            change_detection_ran=global_change_detection_ran,
            all_document_ids=all_document_ids,
            raw_chunks_by_doc=global_raw_chunks_by_doc,
        )

        logger.info(
            "Running finalize steps for collection %s", collection_name,
        )
        await self._run_steps(self._finalize_steps, finalize_ctx)

        return self._build_result(finalize_ctx, len(documents))

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _run_steps(
        self,
        steps: list[PipelineStep],
        context: PipelineContext,
        *,
        metrics_suffix: str = "",
    ) -> None:
        for step in steps:
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
                context.metrics[f"{step.name}{metrics_suffix}"] = StepMetrics(
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
            context.metrics[f"{step.name}{metrics_suffix}"] = StepMetrics(
                duration=elapsed,
                items_in=items_before,
                items_out=len(context.chunks),
                error_count=len(context.errors) - errors_before,
            )

    @staticmethod
    def _build_result(context: PipelineContext, doc_count: int) -> IngestResult:
        return IngestResult(
            collection_name=context.collection_name,
            documents_processed=doc_count,
            chunks_stored=context.chunks_stored,
            errors=context.errors,
            success=len(context.errors) == 0,
            chunks_skipped=context.chunks_skipped,
            chunks_deleted=context.chunks_deleted,
        )
