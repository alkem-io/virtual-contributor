"""The retry log must not carry a member's search terms.

``query_lexical`` sends the member's own words to the store in
``where_document``. Chroma's validation errors interpolate that whole filter
into their message, so an unredacted retry warning would write the member's
query into the log — going around the redaction the fusion layer applies when
the lexical arm fails.
"""

from __future__ import annotations

import logging
import json

import pytest

from core.adapters.chromadb import ChromaDBAdapter


class _Embeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 4 for _ in texts]


#: A term distinctive enough that finding it in a log is unambiguous.
SECRET_TERM = "myrarediseasename"


class _ExplodingCollection:
    """Stands in for a store that echoes the filter back in its error.

    This is Chroma's own behaviour: ``chromadb.api.types.validate_where_document``
    formats the ``where_document`` dict straight into the ``ValueError``.
    """

    def query(self, **kwargs):
        raise ValueError(
            f"Expected where document to have exactly one operator, got "
            f"{kwargs}"
        )


class _ExplodingClient:
    def get_or_create_collection(self, *args, **kwargs):
        return _ExplodingCollection()


@pytest.fixture
def adapter(monkeypatch) -> ChromaDBAdapter:
    monkeypatch.setattr(
        "chromadb.HttpClient", lambda **kwargs: _ExplodingClient()
    )
    return ChromaDBAdapter(host="localhost", embeddings=_Embeddings())


@pytest.fixture(autouse=True)
def _no_backoff_delay(monkeypatch):
    """Retries here are about logging, not timing — don't sleep through them."""
    monkeypatch.setattr("core.adapters.chromadb.BASE_DELAY", 0.0)


class TestLexicalRetryLogging:
    async def test_member_terms_never_reach_the_log(self, adapter, caplog):
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError):
                await adapter.query_lexical(
                    collection="c", terms=[SECRET_TERM, "ingress"],
                )

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert logged, "expected at least one retry warning"
        assert SECRET_TERM not in logged, (
            f"member's search term leaked into the retry log:\n{logged}"
        )

    async def test_the_exception_type_is_still_reported(self, adapter, caplog):
        """Redaction must not make the failure invisible to an operator."""
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError):
                await adapter.query_lexical(collection="c", terms=[SECRET_TERM])

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "ValueError" in logged

    async def test_the_exception_itself_is_unchanged(self, adapter):
        """Only the log is narrowed; the caller still sees the real error."""
        with pytest.raises(ValueError, match=SECRET_TERM):
            await adapter.query_lexical(collection="c", terms=[SECRET_TERM])


class TestOtherOperationsStillLogDetail:
    """Redaction is scoped to the member-derived call, not applied everywhere."""

    async def test_dense_query_keeps_its_message(self, adapter, caplog):
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError):
                await adapter.query(collection="c", query_texts=["anything"])

        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "Expected where document" in logged

    async def test_filtered_dense_query_redacts_branch_id_but_keeps_type(self, adapter, caplog):
        branch_id = "private-branch-identifier"
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ValueError):
                await adapter.query(
                    collection="c", query_texts=["anything"],
                    where={"subspaceId": {"$eq": branch_id}},
                )
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert branch_id not in logged
        assert "ValueError" in logged

    @pytest.mark.parametrize(
        ("error", "type_name"),
        [
            (RuntimeError("private-branch-identifier"), "RuntimeError"),
            (json.JSONDecodeError("private-branch-identifier", "{", 0), "JSONDecodeError"),
        ],
    )
    async def test_filtered_retry_errors_redact_branch_id_and_keep_retry_state(
        self, error, type_name, caplog,
    ):
        attempts = 0

        def explode():
            nonlocal attempts
            attempts += 1
            raise error

        with caplog.at_level(logging.WARNING):
            with pytest.raises(type(error)):
                await ChromaDBAdapter._retry(explode, redact_errors=True)
        logged = "\n".join(record.getMessage() for record in caplog.records)
        assert attempts == 3
        assert "private-branch-identifier" not in logged
        assert type_name in logged
        assert "attempt 1 failed, retrying" in logged
