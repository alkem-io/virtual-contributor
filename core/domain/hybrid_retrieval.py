"""Run the embedding and lexical arms together and fuse what they return.

This is the single place where two rankings become one. Everything downstream —
the relevance threshold, the context budget, source attribution — sees one
ranked set and does not know it was assembled from two.

Disabled, this is a passthrough: the embedding query is made exactly as before
and returned untouched, with no lexical call at all. That is what makes the
switch a real rollback rather than a different code path that merely resembles
the old one.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from core.domain.query_terms import extract_terms
from core.domain.rank_fusion import reciprocal_rank_fusion
from core.ports.knowledge_store import KnowledgeStorePort, QueryResult
from core.ports.embeddings import EmbeddingError

logger = logging.getLogger(__name__)


class HybridSettings(Protocol):
    """The configuration this module reads.

    Declared structurally so the fusion path does not depend on the whole
    application config object — anything carrying these values will do, which
    keeps the tests honest.
    """

    hybrid_retrieval_enabled: bool
    hybrid_dense_weight: float
    hybrid_lexical_weight: float
    hybrid_rrf_k: int
    hybrid_max_terms: int
    hybrid_min_term_len: int


def _empty() -> QueryResult:
    return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])


def _count(result: QueryResult) -> int:
    return len(result.ids[0]) if result.ids else 0


async def retrieve(
    store: KnowledgeStorePort,
    collection: str,
    query: str,
    config: Any,
    *,
    n_results: int = 10,
    where: dict | None = None,
) -> QueryResult:
    """Retrieve passages for ``query``, by meaning and by wording.

    The embedding arm's failure propagates: it is the primary arm, and an
    answer built without it would be quietly worse than no answer. The lexical
    arm's failure does not — it is an enhancement, and losing it should degrade
    retrieval to what it was before this feature, not fail the request.
    """
    if not getattr(config, "hybrid_retrieval_enabled", False):
        return await store.query(
            collection=collection, query_texts=[query], n_results=n_results,
            where=where,
        )

    dense_weight = getattr(config, "hybrid_dense_weight", 1.0)
    lexical_weight = getattr(config, "hybrid_lexical_weight", 1.0)

    # A zero weight mutes an arm. Muted means *not consulted*: not queried, not
    # fused, and — for the dense arm — not able to fail the request. Querying it
    # anyway and then multiplying by zero is not the same thing, because RRF
    # keeps a document that any arm returned. Its ids would still surface
    # whenever fewer than ``n_results`` documents have a positive score, which
    # is exactly the comparison-against-baseline this switch exists to make.
    dense_muted = dense_weight == 0
    lexical_muted = lexical_weight == 0

    if lexical_muted:
        # Nothing to fuse and nothing to ask: the capability check and term
        # extraction below are both work done solely for an arm that is off.
        logger.debug(
            "Hybrid retrieval: lexical arm muted by zero weight, dense only"
        )
        return await store.query(
            collection=collection, query_texts=[query], n_results=n_results,
            where=where,
        )

    query_lexical = getattr(store, "query_lexical", None)
    if query_lexical is None:
        # A store predating this feature. Retrieval is still correct without a
        # lexical arm, so the request proceeds rather than failing on a
        # capability it never needed.
        logger.warning(
            "Hybrid retrieval is enabled but %s provides no lexical query; "
            "using semantic results only",
            type(store).__name__,
        )
        return await store.query(
            collection=collection, query_texts=[query], n_results=n_results,
            where=where,
        )

    terms = extract_terms(
        query,
        min_len=config.hybrid_min_term_len,
        max_terms=config.hybrid_max_terms,
    )
    if not terms:
        # Nothing in the question is worth matching literally — a question made
        # entirely of common words would match everything, which discriminates
        # between nothing.
        logger.debug("Hybrid retrieval: no lexical terms in query, dense only")
        return await store.query(
            collection=collection, query_texts=[query], n_results=n_results,
            where=where,
        )

    if dense_muted:
        # The dense arm is off, so its failure cannot be "the primary arm
        # failed" — there is no primary arm. Querying it to then discard the
        # result would let a broken embedding backend fail a request that was
        # deliberately configured not to use it. Configuration forbids both
        # weights being zero, so the lexical arm is live here.
        logger.debug(
            "Hybrid retrieval: dense arm muted by zero weight, lexical only"
        )
        try:
            return await query_lexical(
                collection=collection, terms=terms, n_results=n_results,
                where=where,
            )
        except EmbeddingError:
            # A typed query-embedding failure is a terminal retrieval
            # boundary, even when the dense arm was deliberately muted.
            raise
        except Exception as exc:
            logger.warning(
                "Lexical retrieval failed for collection %s (%s) with the "
                "dense arm muted; returning no results",
                collection, type(exc).__name__,
            )
            return _empty()

    # One gather, so the lexical arm's latency overlaps the embedding arm's
    # rather than being added to it. Every answer pays the wall-clock cost of
    # the slower arm, not the sum.
    dense_result, lexical_result = await asyncio.gather(
        store.query(
            collection=collection, query_texts=[query], n_results=n_results,
            where=where,
        ),
        query_lexical(
            collection=collection, terms=terms, n_results=n_results,
            where=where,
        ),
        return_exceptions=True,
    )

    if isinstance(dense_result, BaseException):
        raise dense_result

    if isinstance(lexical_result, BaseException):
        if isinstance(lexical_result, EmbeddingError):
            raise lexical_result
        # The exception type, not its message: a store error can echo the
        # member's own query terms back into the log.
        logger.warning(
            "Lexical retrieval failed for collection %s (%s), continuing with "
            "semantic results only",
            collection, type(lexical_result).__name__,
        )
        lexical_result = _empty()

    fused = reciprocal_rank_fusion(
        [dense_result, lexical_result],
        k=config.hybrid_rrf_k,
        weights=[config.hybrid_dense_weight, config.hybrid_lexical_weight],
        limit=n_results,
    )

    dense_ids = set(dense_result.ids[0]) if dense_result.ids else set()
    lexical_ids = set(lexical_result.ids[0]) if lexical_result.ids else set()
    logger.info(
        "Hybrid retrieval on %s: %d semantic, %d lexical, %d in both, "
        "%d after fusion",
        collection, _count(dense_result), _count(lexical_result),
        len(dense_ids & lexical_ids), _count(fused),
    )
    return fused
