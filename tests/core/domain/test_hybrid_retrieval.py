"""Two-arm retrieval: enablement, degradation, and concurrency."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import pytest

from core.domain.hybrid_retrieval import retrieve
from core.ports.knowledge_store import QueryResult
from tests.conftest import MockKnowledgeStorePort


@dataclass
class _Settings:
    hybrid_retrieval_enabled: bool = True
    hybrid_dense_weight: float = 1.0
    hybrid_lexical_weight: float = 1.0
    hybrid_rrf_k: int = 60
    hybrid_max_terms: int = 8
    hybrid_min_term_len: int = 3


def _result(ids: list[str], *, lexical: bool = False) -> QueryResult:
    return QueryResult(
        documents=[[f"doc-{i}" for i in ids]],
        metadatas=[[{"documentId": i} for i in ids]],
        distances=[[None if lexical else 0.1] * len(ids)],
        ids=[list(ids)],
    )


class _FakeStore(MockKnowledgeStorePort):
    def __init__(self, *, dense=None, lexical=None, dense_error=None,
                 lexical_error=None, delay=0.0):
        self._dense = dense if dense is not None else _result(["a", "b"])
        self._lexical = lexical if lexical is not None else _result(["c"], lexical=True)
        self._dense_error = dense_error
        self._lexical_error = lexical_error
        self._delay = delay
        super().__init__()

    async def query(self, collection, query_texts, n_results=10, where=None):
        self.query_calls.append((collection, query_texts, n_results))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._dense_error:
            raise self._dense_error
        return self._dense

    async def query_lexical(self, collection, terms, n_results=10, where=None):
        self.lexical_calls.append((collection, terms, n_results))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._lexical_error:
            raise self._lexical_error
        return self._lexical


class TestDisabled:
    async def test_returns_the_dense_result_untouched(self):
        """Disabled must be a real rollback, not a similar-looking path."""
        dense = _result(["a", "b", "c"])
        store = _FakeStore(dense=dense)
        out = await retrieve(store, "c", "traefik ingress",
                             _Settings(hybrid_retrieval_enabled=False))
        assert out is dense

    async def test_never_touches_the_lexical_arm(self):
        store = _FakeStore()
        await retrieve(store, "c", "traefik ingress",
                       _Settings(hybrid_retrieval_enabled=False))
        assert store.lexical_calls == []


class TestEnabled:
    async def test_both_arms_are_queried(self):
        store = _FakeStore()
        await retrieve(store, "c", "traefik ingress config", _Settings())
        assert len(store.query_calls) == 1
        assert len(store.lexical_calls) == 1

    async def test_lexical_only_passage_appears_in_the_result(self):
        store = _FakeStore(dense=_result(["a"]),
                           lexical=_result(["rare"], lexical=True))
        out = await retrieve(store, "c", "rare identifier here", _Settings())
        assert "rare" in out.ids[0]

    async def test_terms_are_extracted_from_the_question(self):
        store = _FakeStore()
        await retrieve(store, "c", "What is the Traefik setup?", _Settings())
        _, terms, _ = store.lexical_calls[0]
        assert "traefik" in terms
        assert "what" not in terms

    async def test_a_question_of_only_common_words_skips_the_lexical_arm(self):
        """Matching on "the" returns everything, which discriminates nothing."""
        store = _FakeStore()
        await retrieve(store, "c", "what is the and or", _Settings())
        assert store.lexical_calls == []
        assert len(store.query_calls) == 1


class TestDegradation:
    async def test_lexical_failure_still_answers(self, caplog):
        import logging

        store = _FakeStore(dense=_result(["a", "b"]),
                           lexical_error=RuntimeError("store unavailable"))
        with caplog.at_level(logging.WARNING):
            out = await retrieve(store, "c", "traefik ingress", _Settings())
        assert out.ids[0] == ["a", "b"]
        assert any("lexical" in r.message.lower() for r in caplog.records)

    async def test_dense_failure_propagates(self):
        """The primary arm failing must not be papered over."""
        store = _FakeStore(dense_error=RuntimeError("store unavailable"))
        with pytest.raises(RuntimeError, match="store unavailable"):
            await retrieve(store, "c", "traefik ingress", _Settings())

    async def test_empty_lexical_arm_preserves_dense_order(self):
        store = _FakeStore(dense=_result(["a", "b", "c"]),
                           lexical=_result([], lexical=True))
        out = await retrieve(store, "c", "traefik ingress", _Settings())
        assert out.ids[0] == ["a", "b", "c"]


class TestConcurrency:
    async def test_arms_run_concurrently(self):
        """The lexical arm must overlap the dense one, not queue behind it."""
        delay = 0.05
        store = _FakeStore(delay=delay)
        started = time.perf_counter()
        await retrieve(store, "c", "traefik ingress config", _Settings())
        elapsed = time.perf_counter() - started
        assert elapsed < delay * 1.8, (
            f"arms appear serialised: {elapsed:.3f}s for two {delay}s arms"
        )


class TestMutedArms:
    """A zero weight means an arm is off, not that it scores zero.

    RRF keeps every document any arm returned, so a "muted" arm that is still
    queried leaks its ids into the output whenever fewer than ``n_results``
    documents carry a positive score — which is exactly the baseline
    comparison a zero weight is set to make.
    """

    async def test_muted_lexical_arm_is_not_queried(self):
        store = _FakeStore()
        await retrieve(store, "c", "traefik ingress config",
                       _Settings(hybrid_lexical_weight=0.0))
        assert store.lexical_calls == []

    async def test_muted_lexical_results_never_reach_the_output(self):
        store = _FakeStore(dense=_result(["a"]),
                           lexical=_result(["lex"], lexical=True))
        out = await retrieve(store, "c", "traefik ingress config",
                             _Settings(hybrid_lexical_weight=0.0), n_results=5)
        assert out.ids[0] == ["a"]
        assert "lex" not in out.ids[0]

    async def test_muted_dense_arm_is_not_queried(self):
        store = _FakeStore()
        await retrieve(store, "c", "traefik ingress config",
                       _Settings(hybrid_dense_weight=0.0))
        assert store.query_calls == []

    async def test_muted_dense_results_never_reach_the_output(self):
        store = _FakeStore(dense=_result(["a"]),
                           lexical=_result(["lex"], lexical=True))
        out = await retrieve(store, "c", "traefik ingress config",
                             _Settings(hybrid_dense_weight=0.0), n_results=5)
        assert out.ids[0] == ["lex"]
        assert "a" not in out.ids[0]

    async def test_a_muted_dense_arm_cannot_fail_the_request(self):
        """It was configured out of the request; it must not break it."""
        store = _FakeStore(dense_error=RuntimeError("embeddings backend down"),
                           lexical=_result(["lex"], lexical=True))
        out = await retrieve(store, "c", "traefik ingress config",
                             _Settings(hybrid_dense_weight=0.0))
        assert out.ids[0] == ["lex"]

    async def test_a_muted_lexical_arm_skips_term_extraction(self):
        """No store lacks the capability badly enough to matter when it's off."""
        class _NoLexical:
            def __init__(self):
                self.query_calls = []

            async def query(self, collection, query_texts, n_results=10, where=None):
                self.query_calls.append((collection, query_texts, n_results))
                return _result(["a"])

        store = _NoLexical()
        out = await retrieve(store, "c", "traefik ingress config",
                             _Settings(hybrid_lexical_weight=0.0))
        assert out.ids[0] == ["a"]
        assert len(store.query_calls) == 1

    async def test_lexical_failure_with_dense_muted_yields_no_results(self):
        store = _FakeStore(lexical_error=RuntimeError("store unavailable"))
        out = await retrieve(store, "c", "traefik ingress config",
                             _Settings(hybrid_dense_weight=0.0))
        assert out.ids[0] == []
