"""Expert retrieval with the lexical arm: what it finds, and what it preserves."""

from __future__ import annotations

from dataclasses import dataclass

from core.events.input import Input
from core.ports.knowledge_store import QueryResult
from plugins.expert.plugin import ExpertPlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


async def test_traced_hybrid_waiter_cancellation_preserves_single_flight_and_cleanup() -> None:
    import asyncio
    import contextvars
    from unittest.mock import patch
    import httpx
    from core.adapters.chromadb import ChromaDBAdapter
    from core.adapters.openai_compatible_embeddings import OpenAICompatibleEmbeddingsAdapter
    from core.tracing_knowledge_store import TracedKnowledgeStore

    adapter = ChromaDBAdapter.__new__(ChromaDBAdapter)
    adapter._query_embedding_cache = contextvars.ContextVar("traced-cancel", default=None)
    first_started, release_first, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    attempts = 0
    embeddings = OpenAICompatibleEmbeddingsAdapter.__new__(OpenAICompatibleEmbeddingsAdapter)
    embeddings._query_instruction = ""
    embeddings._query_max_utf8_bytes = 32768
    embeddings._api_key, embeddings._endpoint, embeddings._model_name = "key", "http://provider", "model"
    embeddings._max_attempts, embeddings._attempt_timeout_seconds, embeddings._total_deadline_seconds = 2, 5, 30
    adapter._embeddings = embeddings

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def post(self, *args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                first_started.set()
                await release_first.wait()
                raise httpx.ConnectError("first attempt")
            second_started.set()
            await asyncio.Event().wait()

    class Store(MockKnowledgeStorePort):
        def query_embedding_scope(self):
            return adapter.query_embedding_scope()
        async def query(self, *args, **kwargs):
            await adapter._embed_query(["same"])
            return QueryResult([[]], [[]], [[]], [[]])
        async def query_lexical(self, *args, **kwargs):
            await adapter._embed_query(["same"])
            return QueryResult([[]], [[]], [[]], [[]])

    store = TracedKnowledgeStore(Store())
    with patch("core.adapters.openai_compatible_embeddings.httpx.AsyncClient", return_value=Client()), patch(
        "core.adapters.openai_compatible_embeddings.BASE_DELAY", 0,
    ):
        async with store.query_embedding_scope():
            installer = asyncio.create_task(store.query("c", ["same"]))
            await first_started.wait()
            follower = asyncio.create_task(store.query_lexical("c", ["same"]))
            installer.cancel()
            follower.cancel()
            import pytest
            with pytest.raises(asyncio.CancelledError):
                await installer
            with pytest.raises(asyncio.CancelledError):
                await follower
            cache = adapter._query_embedding_cache.get()
            assert cache is not None
            provider = cache[("same",)]
            assert isinstance(provider, asyncio.Task) and not provider.done()
            release_first.set()
            await second_started.wait()
            assert not provider.done()  # both cancelled waiters left it owned by the scope
        assert provider.done() and provider.cancelled()
    assert attempts == 2
    assert adapter._query_embedding_cache.get() is None


@dataclass
class _Hybrid:
    hybrid_retrieval_enabled: bool = True
    hybrid_dense_weight: float = 1.0
    hybrid_lexical_weight: float = 1.0
    hybrid_rrf_k: int = 60
    hybrid_max_terms: int = 8
    hybrid_min_term_len: int = 3


class _Store(MockKnowledgeStorePort):
    """Mock whose dense arm deliberately ranks the term-bearing passage last.

    That is the situation this feature exists for: a passage whose wording
    matches exactly but whose embedding similarity is unremarkable.
    """

    def __init__(self, dense_ids: list[str], corpus: dict[str, str]):
        super().__init__()
        self._dense_ids = dense_ids
        self._corpus = corpus
        self.collections["c-knowledge"] = [
            {"id": i, "document": text, "metadata": {"documentId": i, "source": i}}
            for i, text in corpus.items()
        ]

    async def query(self, collection, query_texts, n_results=10, where=None):
        self.query_calls.append((collection, query_texts, n_results))
        ids = self._dense_ids[:n_results]
        return QueryResult(
            documents=[[self._corpus[i] for i in ids]],
            metadatas=[[{"documentId": i, "source": i} for i in ids]],
            distances=[[0.2 + 0.1 * n for n in range(len(ids))]],
            ids=[list(ids)],
        )


async def test_concurrent_hybrid_arms_share_one_exact_embedding_submission() -> None:
    """Expert opens one real request scope around both hybrid arms."""
    import contextvars
    from core.adapters.chromadb import ChromaDBAdapter

    adapter = ChromaDBAdapter.__new__(ChromaDBAdapter)
    adapter._query_embedding_cache = contextvars.ContextVar("expert-scope", default=None)
    adapter._embeddings = type("Embeddings", (), {})()
    gate = __import__("asyncio").Event()
    calls = 0
    async def embed_query(texts):
        nonlocal calls
        calls += 1
        await gate.wait()
        return [[.1]]
    adapter._embeddings.embed_query = embed_query

    class Store(MockKnowledgeStorePort):
        def query_embedding_scope(self):
            return adapter.query_embedding_scope()
        async def query(self, *args, **kwargs):
            return await adapter._embed_query(["same"]) and QueryResult([[]], [[]], [[]], [[]])
        async def query_lexical(self, *args, **kwargs):
            return await adapter._embed_query(["same"]) and QueryResult([[]], [[]], [[]], [[]])

    plugin = _plugin(Store(), hybrid=_Hybrid())
    task = __import__("asyncio").create_task(plugin.handle(_event("same")))
    await __import__("asyncio").sleep(0)
    gate.set()
    await task
    assert calls == 1


async def test_traced_concurrent_hybrid_arms_share_one_retry_ladder() -> None:
    """The tracing wrapper forwards the same scope rather than opening two."""
    from core.tracing_knowledge_store import TracedKnowledgeStore
    import contextvars
    from core.adapters.chromadb import ChromaDBAdapter

    adapter = ChromaDBAdapter.__new__(ChromaDBAdapter)
    adapter._query_embedding_cache = contextvars.ContextVar("traced-expert-scope", default=None)
    outer_calls = 0
    provider_attempts = 0
    first_attempt = __import__("asyncio").Event()
    release_retry = __import__("asyncio").Event()
    class Embeddings:
        async def embed_query(self, texts):
            nonlocal outer_calls
            outer_calls += 1
            async def provider():
                nonlocal provider_attempts
                provider_attempts += 1
                if provider_attempts == 1:
                    first_attempt.set()
                    await release_retry.wait()
                    raise ConnectionError("transient provider failure")
                return [[.1]]
            try:
                return await provider()
            except ConnectionError:
                # The adapter-owned outer operation retries internally; the
                # second hybrid arm must join this same task and ladder.
                return await provider()
    adapter._embeddings = Embeddings()
    class Store(MockKnowledgeStorePort):
        def query_embedding_scope(self):
            return adapter.query_embedding_scope()
        async def query(self, *args, **kwargs):
            await adapter._embed_query(["same"])
            return QueryResult([[]], [[]], [[]], [[]])
        async def query_lexical(self, *args, **kwargs):
            await adapter._embed_query(["same"])
            return QueryResult([[]], [[]], [[]], [[]])
    # Forwarding capability is the contract; retrieval uses the wrapped store.
    store = TracedKnowledgeStore(Store())
    task = __import__("asyncio").create_task(_plugin(store, hybrid=_Hybrid()).handle(_event("same")))
    await first_attempt.wait()
    await __import__("asyncio").sleep(0)
    release_retry.set()
    await task
    assert outer_calls == 1 and provider_attempts == 2


def _plugin(store, *, hybrid) -> ExpertPlugin:
    return ExpertPlugin(
        llm=MockLLMPort(response="answer"),
        knowledge_store=store,
        n_results=3,
        score_threshold=0.3,
        hybrid_config=hybrid,
    )


def _event(message: str) -> Input:
    return make_input(message=message, bodyOfKnowledgeID="c")


CORPUS = {
    "d1": "General discussion about infrastructure and networking topics.",
    "d2": "Notes on deployment strategy and rollout planning.",
    "d3": "The Traefik ingress controller terminates TLS at the edge.",
}


class TestExactTermRetrieval:
    async def test_term_bearing_passage_is_retrieved_and_cited(self):
        """Dense ranks it last and the budget would cut it — lexical rescues it."""
        store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            _event("What does Traefik do?")
        )
        cited = {s.source for s in response.sources}
        assert "d3" in cited

    async def test_casing_does_not_matter_in_either_direction(self):
        for query in ("traefik", "TRAEFIK", "TrAeFiK"):
            store = _Store(dense_ids=["d1"], corpus=CORPUS)
            response = await _plugin(store, hybrid=_Hybrid()).handle(
                _event(f"Tell me about {query}")
            )
            assert "d3" in {s.source for s in response.sources}, query

    async def test_a_lexical_only_passage_has_no_score(self):
        """It was not matched by similarity, so there is no similarity to report."""
        store = _Store(dense_ids=["d1"], corpus=CORPUS)
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            _event("Tell me about Traefik")
        )
        lexical = [s for s in response.sources if s.source == "d3"]
        assert lexical and lexical[0].score is None

    async def test_punctuation_in_a_query_does_not_break_retrieval(self):
        """A member's own punctuation must never error their own search."""
        for query in ("What about C++?", "the [draft] policy", "a|b routing", "cost ~50%"):
            store = _Store(dense_ids=["d1"], corpus=CORPUS)
            response = await _plugin(store, hybrid=_Hybrid()).handle(_event(query))
            assert response.result == "answer", query


class TestDisabledParity:
    """With the flag off, retrieval must be what it was before this feature."""

    async def test_same_sources_as_the_dense_path(self):
        off_store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        off = await _plugin(off_store, hybrid=None).handle(
            _event("What does Traefik do?")
        )
        assert [s.source for s in off.sources] == ["d1", "d2"]

    async def test_the_lexical_arm_is_never_consulted(self):
        store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        await _plugin(store, hybrid=None).handle(_event("What does Traefik do?"))
        assert store.lexical_calls == []

    async def test_explicitly_disabled_matches_absent_config(self):
        a = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        b = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        r_none = await _plugin(a, hybrid=None).handle(_event("Traefik?"))
        r_off = await _plugin(
            b, hybrid=_Hybrid(hybrid_retrieval_enabled=False),
        ).handle(_event("Traefik?"))
        assert [s.source for s in r_none.sources] == [s.source for s in r_off.sources]
        assert b.lexical_calls == []


class TestConceptualQueriesAreUnharmed:
    async def test_dense_results_survive_fusion(self):
        """Adding an arm must not remove what the other one found."""
        store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            _event("How should we plan the rollout?")
        )
        cited = {s.source for s in response.sources}
        assert {"d1", "d2"} <= cited


class TestRaggedDistancesKeepDevelopBehaviour:
    """A missing distance is not the same as an absent one.

    An explicit None means "matched literally" and is exempt from the semantic
    threshold. A distance simply missing from a short list is a malformed
    result, which scored zero and was dropped before this feature — and must
    still be, or turning the flag off would not restore prior behaviour.
    """

    @staticmethod
    def _kept(distances: list, threshold: float = 0.3) -> list[str]:
        from plugins.expert.plugin import _filter_and_format

        result = QueryResult(
            documents=[["a", "b"]], metadatas=[[{}, {}]],
            distances=[distances], ids=[["i1", "i2"]],
        )
        _, filtered = _filter_and_format(result, threshold)
        return filtered.documents[0]

    def test_no_distances_drops_everything_as_before(self):
        assert self._kept([]) == []

    def test_a_short_distance_list_drops_the_unmeasured_tail(self):
        assert self._kept([0.1]) == ["a"]

    def test_an_explicit_none_is_still_exempt(self):
        assert self._kept([0.1, None]) == ["a", "b"]

    def test_a_high_distance_is_still_filtered(self):
        assert self._kept([0.1, 0.95]) == ["a"]
