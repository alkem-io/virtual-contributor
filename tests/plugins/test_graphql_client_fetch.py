"""Unit tests for GraphQLClient._rewrite_alkemio_uri() and fetch_url()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from plugins.ingest_space.graphql_client import GraphQLClient


def _make_client(
    endpoint: str = "https://dev.alkemio.org/api/private/non-interactive/graphql",
) -> GraphQLClient:
    """Instantiate a GraphQLClient without triggering real auth."""
    return GraphQLClient(
        graphql_endpoint=endpoint,
        kratos_public_url="https://kratos.example.com",
        email="test@example.com",
        password="secret",
    )


class TestRewriteAlkemioUri:
    """Tests for URI rewriting of Alkemio storage URIs."""

    def test_rewrites_api_prefix(self):
        client = _make_client()
        result = client._rewrite_alkemio_uri(
            "https://alkem.io/api/private/rest/storage/document/abc"
        )
        assert result.startswith("https://dev.alkemio.org/api/private/rest/storage/document/abc")

    def test_external_url_unchanged(self):
        client = _make_client()
        result = client._rewrite_alkemio_uri("https://example.com/page")
        assert result == "https://example.com/page"

    def test_empty_string_unchanged(self):
        client = _make_client()
        result = client._rewrite_alkemio_uri("")
        assert result == ""

    def test_rewrites_rest_prefix(self):
        client = _make_client()
        result = client._rewrite_alkemio_uri("https://alkem.io/rest/something")
        assert result.startswith("https://dev.alkemio.org/rest/something")

    def test_preserves_query_and_fragment(self):
        client = _make_client()
        result = client._rewrite_alkemio_uri(
            "https://alkem.io/api/files?id=1#section"
        )
        assert "id=1" in result
        assert "#section" in result
        assert result.startswith("https://dev.alkemio.org/")

    def test_no_path_external(self):
        """URL with no recognisable Alkemio path is left alone."""
        client = _make_client()
        url = "https://cdn.example.com/assets/image.png"
        assert client._rewrite_alkemio_uri(url) == url


class TestFetchUrl:
    """Tests for GraphQLClient.fetch_url()."""

    async def test_successful_fetch(self):
        client = _make_client()
        client._session_token = "token-123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf; charset=binary"}
        mock_response.content = b"%PDF-data"

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("plugins.ingest_space.graphql_client.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.fetch_url("https://example.com/doc.pdf")

        assert result is not None
        body, content_type = result
        assert body == b"%PDF-data"
        assert content_type == "application/pdf"

    async def test_non_200_returns_none(self):
        client = _make_client()
        client._session_token = "token-123"

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("plugins.ingest_space.graphql_client.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.fetch_url("https://example.com/missing")

        assert result is None

    async def test_body_exceeding_max_bytes_returns_none(self):
        client = _make_client()
        client._session_token = "token-123"

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"x" * 100

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("plugins.ingest_space.graphql_client.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.fetch_url("https://example.com/big.pdf", max_bytes=50)

        assert result is None

    async def test_network_error_returns_none(self):
        client = _make_client()
        client._session_token = "token-123"

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("plugins.ingest_space.graphql_client.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.fetch_url("https://example.com/down")

        assert result is None

    async def test_auto_authenticates_when_no_token(self):
        client = _make_client()
        assert client._session_token is None

        # authenticate() should set the token
        async def fake_auth():
            client._session_token = "fresh-token"

        client.authenticate = AsyncMock(side_effect=fake_auth)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.content = b"hello"

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=False)

        with patch("plugins.ingest_space.graphql_client.httpx.AsyncClient", return_value=mock_http_client):
            result = await client.fetch_url("https://example.com/page")

        client.authenticate.assert_awaited_once()
        assert result is not None
        body, ct = result
        assert body == b"hello"

    async def test_auth_failure_returns_none(self):
        client = _make_client()
        assert client._session_token is None

        client.authenticate = AsyncMock(side_effect=RuntimeError("auth down"))

        result = await client.fetch_url("https://example.com/page")
        assert result is None
