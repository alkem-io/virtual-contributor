from __future__ import annotations

import asyncio
import logging
import json
import re
from typing import Any, Protocol

import chromadb

from core.ports.knowledge_store import GetResult, QueryResult

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


class EmbedFn(Protocol):
    """Minimal protocol for an async embed function."""
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, texts: list[str]) -> list[list[float]]: ...


class ChromaDBAdapter:
    """ChromaDB knowledge store adapter behind KnowledgeStorePort."""

    def __init__(
        self,
        host: str,
        port: int = 8765,
        credentials: str | None = None,
        embeddings: EmbedFn | None = None,
        distance_fn: str = "cosine",
    ) -> None:
        settings = chromadb.config.Settings()
        if credentials:
            settings = chromadb.config.Settings(
                chroma_client_auth_provider="chromadb.auth.token_authn.TokenAuthClientProvider",
                chroma_client_auth_credentials=credentials,
            )
        self._client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=settings,
        )
        self._embeddings = embeddings
        self._distance_fn = distance_fn

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
        where: dict | None = None,
    ) -> QueryResult:
        if self._embeddings is None:
            raise ValueError(
                "ChromaDBAdapter requires an embeddings provider when "
                "embedding_function=None"
            )
        query_embeddings = await self._embeddings.embed_query(query_texts)

        def _query():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            kwargs: dict[str, Any] = {
                "query_embeddings": query_embeddings,
                "n_results": n_results,
            }
            if where is not None:
                kwargs["where"] = where
            results = col.query(**kwargs)
            return QueryResult(
                documents=results.get("documents", []),
                metadatas=results.get("metadatas", []),
                distances=results.get("distances") or [],
                ids=results.get("ids", []),
            )

        return await self._retry(_query)

    @staticmethod
    def _document_predicate(terms: list[str]) -> dict:
        """Build a case-insensitive literal-match predicate over document text.

        ``$regex`` rather than ``$contains``: the latter is case-sensitive, so
        a member asking about "traefik" would not match a passage saying
        "Traefik" — silently failing at exactly the exact-name matching this
        arm exists to provide.

        Every term is escaped. A member's query is text, not a pattern: left
        raw, punctuation like ``C++`` changes what matches, and an unbalanced
        bracket is rejected by the store outright, so a member's own question
        would error their own search.

        A single term uses the bare form — the store rejects a one-element
        ``$or``.
        """
        predicates = [
            {"$regex": f"(?i){re.escape(term)}"} for term in terms
        ]
        if len(predicates) == 1:
            return predicates[0]
        return {"$or": predicates}

    async def query_lexical(
        self,
        collection: str,
        terms: list[str],
        n_results: int = 10,
        where: dict | None = None,
    ) -> QueryResult:
        if not terms:
            # Nothing to match literally — say so without troubling the store.
            return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])
        if self._embeddings is None:
            raise ValueError(
                "ChromaDBAdapter requires an embeddings provider when "
                "embedding_function=None"
            )

        # The store has no text-only query: a vector is still required, and the
        # document predicate narrows the candidates it ranks.
        query_embeddings = await self._embeddings.embed_query([" ".join(terms)])
        where_document = self._document_predicate(terms)

        def _query():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            kwargs: dict = dict(
                query_embeddings=query_embeddings,
                n_results=n_results,
                where_document=where_document,
            )
            # The metadata filter applies to BOTH arms: without it the
            # lexical arm resurfaces exactly the entries — summaries — that
            # the dense arm's filter excludes, and fusion re-admits them.
            if where is not None:
                kwargs["where"] = where
            results = col.query(**kwargs)
            ids = results.get("ids", []) or [[]]
            # Matching is a yes/no, so there is no lexical distance to report.
            # None rather than 0.0: a fabricated zero would read downstream as
            # a perfect semantic match.
            distances: list[list[float | None]] = [
                [None] * len(row) for row in ids
            ]
            return QueryResult(
                documents=results.get("documents", []) or [[]],
                metadatas=results.get("metadatas", []) or [[]],
                distances=distances,
                ids=ids,
            )

        # Redacted: this call carries the member's own search terms in
        # ``where_document``, and the store echoes the whole filter back in its
        # validation errors. An unredacted retry warning would write those terms
        # to the log, going around the redaction the fusion layer applies when
        # the lexical arm fails.
        return await self._retry(_query, redact_errors=True)

    async def ingest(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        if embeddings is None:
            raise ValueError(
                "Precomputed embeddings are required when embedding_function=None"
            )

        def _ingest():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            col.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids,
                embeddings=embeddings,
            )

        await self._retry(_ingest)

    async def delete_collection(self, collection: str) -> None:
        def _delete():
            try:
                self._client.delete_collection(collection)
            except Exception as exc:
                msg = str(exc).lower()
                if "not found" in msg or "does not exist" in msg:
                    logger.warning("Collection %s not found for deletion, skipping", collection)
                    return
                raise

        await self._retry(_delete)

    async def get(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> GetResult:
        def _get():
            col = self._client.get_or_create_collection(
                collection,
                embedding_function=None,
                metadata={"hnsw:space": self._distance_fn},
            )
            kwargs: dict = {}
            if ids is not None:
                kwargs["ids"] = ids
            if where is not None:
                kwargs["where"] = where
            if include is not None:
                kwargs["include"] = include
            result = col.get(**kwargs)
            return GetResult(
                ids=result.get("ids", []),
                metadatas=result.get("metadatas"),
                documents=result.get("documents"),
                embeddings=result.get("embeddings"),
            )

        return await self._retry(_get)

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        def _delete_items():
            try:
                col = self._client.get_or_create_collection(
                    collection,
                    embedding_function=None,
                    metadata={"hnsw:space": self._distance_fn},
                )
                kwargs: dict = {}
                if ids is not None:
                    kwargs["ids"] = ids
                if where is not None:
                    kwargs["where"] = where
                col.delete(**kwargs)
            except Exception as exc:
                msg = str(exc).lower()
                if "not found" in msg or "does not exist" in msg:
                    return
                raise

        await self._retry(_delete_items)

    @staticmethod
    async def _retry(
        fn, max_retries: int = MAX_RETRIES, *, redact_errors: bool = False,
    ) -> Any:
        """Retry ``fn`` with exponential backoff.

        ``redact_errors`` logs only the exception's type, for operations whose
        arguments are derived from a member's query. The exception itself is
        still raised unchanged — the caller decides what to do with it; only
        what this adapter *writes to the log* is narrowed.
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await asyncio.to_thread(fn)
            except ValueError as exc:
                # Client-side validation errors (e.g. a malformed `where`
                # filter) are deterministic — retrying burns backoff sleeps
                # for the same rejection. Surface them immediately. But
                # JSONDecodeError (a ValueError subclass) means a transient
                # truncated/non-JSON body on an otherwise-successful response
                # (the client's orjson.loads response-parse step — e.g. a
                # connection cut mid-body) — that one stays retryable.
                # NOTE: proxy 502s raise a bare Exception in the chromadb
                # client and are retried by the generic branch below.
                if not isinstance(exc, json.JSONDecodeError):
                    # Fail fast, but not silently: the operator still needs to
                    # see that the store rejected the call. #114's redaction
                    # applies here too — a lexical predicate embeds the
                    # member's search terms, and Chroma echoes it back in the
                    # ValueError, so the redacted variant logs only the type.
                    detail = type(exc).__name__ if redact_errors else exc
                    logger.warning(
                        "ChromaDB rejected the call (not retrying): %s", detail,
                    )
                    raise
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning("ChromaDB attempt %d failed, retrying: %s", attempt + 1, exc)
                    await asyncio.sleep(delay)
            except Exception as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    detail = type(exc).__name__ if redact_errors else exc
                    logger.warning(
                        "ChromaDB attempt %d failed, retrying: %s",
                        attempt + 1, detail,
                    )
                    await asyncio.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Retry called with max_retries=0")

    @staticmethod
    def combine_query_results(*results: QueryResult) -> QueryResult:
        """Merge multiple query results into one."""
        combined = QueryResult(documents=[], metadatas=[], distances=[], ids=[])
        for r in results:
            combined.documents.extend(r.documents)
            combined.metadatas.extend(r.metadatas)
            combined.distances.extend(r.distances)
            combined.ids.extend(r.ids)
        return combined
