"""HTTP-boundary tests for safe link fetching and URI rewriting."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from plugins import url_guard
from plugins.ingest_space.graphql_client import GraphQLClient, MAX_REDIRECT_HOPS
from plugins.url_guard import RefusalCategory


PUBLIC_ADDRESS = "93.184.216.34"


def _make_client(
    endpoint: str = "https://deployment.example/api/private/non-interactive/graphql",
) -> GraphQLClient:
    return GraphQLClient(
        graphql_endpoint=endpoint,
        kratos_public_url="https://kratos.example.com",
        email="test@example.com",
        password="secret",
    )


def _patch_transport(handler):
    transport = httpx.MockTransport(handler)
    return patch(
        "plugins.ingest_space.graphql_client.httpx.AsyncClient",
        return_value=httpx.AsyncClient(transport=transport),
    )


def _patch_resolver(monkeypatch: pytest.MonkeyPatch, addresses: dict[str, list[str]]) -> None:
    async def resolve_host(host: str) -> list[str]:
        return addresses[host]

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)


class CountingStream(httpx.AsyncByteStream):
    """A body stream that proves callers stop iterating once their cap trips."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.consumed = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed += len(chunk)
            yield chunk

    async def aclose(self) -> None:
        return None


class TestRewriteAlkemioUri:
    def test_rewrites_api_prefix(self):
        result = _make_client()._rewrite_alkemio_uri(
            "https://alkem.io/api/private/rest/storage/document/abc"
        )
        assert result.startswith("https://deployment.example/api/private/rest/storage/document/abc")

    def test_rewrites_rest_prefix(self):
        result = _make_client()._rewrite_alkemio_uri("https://alkem.io/rest/something")
        assert result.startswith("https://deployment.example/rest/something")

    def test_preserves_query_and_fragment(self):
        result = _make_client()._rewrite_alkemio_uri("https://alkem.io/api/files?id=1#section")
        assert result == "https://deployment.example/api/files?id=1#section"

    def test_external_url_unchanged(self):
        url = "https://example.com/page"
        assert _make_client()._rewrite_alkemio_uri(url) == url

    def test_lookalike_is_not_rewritten(self):
        url = "https://evil-alkem.io/api/private/forbidden"
        assert _make_client()._rewrite_alkemio_uri(url) == url

    def test_relative_uri_is_not_rewritten(self):
        assert _make_client()._rewrite_alkemio_uri("/api/private/forbidden") == "/api/private/forbidden"


class TestFetchUrl:
    async def test_successful_public_pdf_fetch(self):
        client = _make_client()
        client._session_token = "token-123"

        with _patch_transport(lambda _: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-data")):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/document.pdf", link_id="link-1")

        assert result == (b"%PDF-data", "application/pdf")

    async def test_non_200_returns_none(self):
        client = _make_client()
        client._session_token = "token-123"

        with _patch_transport(lambda _: httpx.Response(404)):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/missing", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.TRANSPORT

    async def test_body_exceeding_max_bytes_returns_none(self):
        client = _make_client()
        client._session_token = "token-123"
        stream = CountingStream([b"x" * 30, b"x" * 30, b"x" * 100])

        with _patch_transport(lambda _: httpx.Response(200, headers={"content-type": "application/pdf"}, stream=stream)):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/big.pdf", max_bytes=50, link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.SIZE
        assert stream.consumed == 60

    async def test_declared_oversize_body_is_not_read(self):
        client = _make_client()
        client._session_token = "token-123"
        stream = CountingStream([b"x" * 100])

        with _patch_transport(lambda _: httpx.Response(200, headers={"content-type": "application/pdf", "content-length": "100"}, stream=stream)):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/big.pdf", max_bytes=50, link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.SIZE
        assert stream.consumed == 0

    async def test_unsupported_content_type_is_not_embedded(self):
        client = _make_client()
        client._session_token = "token-123"

        with _patch_transport(lambda _: httpx.Response(200, headers={"content-type": "image/png"}, content=b"png")):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/image.png", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.CONTENT_TYPE

    async def test_network_error_returns_none(self):
        client = _make_client()
        client._session_token = "token-123"

        def error_handler(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        with _patch_transport(error_handler):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/down", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.TRANSPORT

    async def test_auto_authenticates_when_no_token(self):
        client = _make_client()

        async def fake_authenticate() -> None:
            client._session_token = "fresh-token"

        client.authenticate = AsyncMock(side_effect=fake_authenticate)
        with _patch_transport(lambda _: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hello")):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/page", link_id="link-1")

        client.authenticate.assert_awaited_once()
        assert result == (b"hello", "text/plain")

    async def test_auth_failure_returns_none(self):
        client = _make_client()
        client.authenticate = AsyncMock(side_effect=RuntimeError("auth down"))

        result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/page", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.TRANSPORT

    @pytest.mark.parametrize("destination", ["169.254.42.42", "127.0.0.1", "10.0.0.1"])
    async def test_redirect_to_denied_destination_is_never_requested(self, destination: str):
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(302, headers={"location": f"http://{destination}/metadata"})

        with _patch_transport(handler):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/start", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.REDIRECT
        assert len(requests) == 1

    async def test_public_redirect_chain_fetches_final_body(self):
        client = _make_client()
        client._session_token = "token-123"
        second_address = "1.1.1.1"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == PUBLIC_ADDRESS:
                return httpx.Response(302, headers={"location": f"https://{second_address}/final.pdf"})
            assert request.url.host == second_address
            return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"public pdf")

        with _patch_transport(handler):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/start", link_id="link-1")

        assert result == (b"public pdf", "application/pdf")

    async def test_public_chain_turning_private_is_refused_at_that_hop(self):
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(302, headers={"location": "https://1.1.1.1/second"})
            return httpx.Response(302, headers={"location": "http://192.168.1.2/final"})

        with _patch_transport(handler):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/start", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.REDIRECT
        assert len(requests) == 2

    async def test_redirect_chain_is_limited(self):
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(302, headers={"location": f"https://{PUBLIC_ADDRESS}/hop-{len(requests)}"})

        with _patch_transport(handler):
            result = await client.fetch_url(f"https://{PUBLIC_ADDRESS}/start", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.HOP_LIMIT
        assert len(requests) == MAX_REDIRECT_HOPS + 1

    async def test_hostname_resolving_private_is_refused_before_transport(self, monkeypatch: pytest.MonkeyPatch):
        _patch_resolver(monkeypatch, {"rebind.example": ["10.0.0.5"]})
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        with _patch_transport(lambda request: requests.append(request) or httpx.Response(200)):
            result = await client.fetch_url("https://rebind.example/document.pdf", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.DESTINATION
        assert requests == []

    async def test_public_hostname_is_connected_through_validated_address(self, monkeypatch: pytest.MonkeyPatch):
        _patch_resolver(monkeypatch, {"public.example": [PUBLIC_ADDRESS]})
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        with _patch_transport(lambda request: requests.append(request) or httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")):
            result = await client.fetch_url("https://public.example/document.txt", link_id="link-1")

        assert result == (b"ok", "text/plain")
        assert requests[0].url.host == PUBLIC_ADDRESS
        assert requests[0].headers["host"] == "public.example"
        assert requests[0].extensions["sni_hostname"] == "public.example"

    async def test_lookalike_never_receives_credentials(self, monkeypatch: pytest.MonkeyPatch):
        _patch_resolver(monkeypatch, {"evil-alkem.io": [PUBLIC_ADDRESS]})
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        with _patch_transport(lambda request: requests.append(request) or httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")):
            result = await client.fetch_url("https://evil-alkem.io/api/private/forbidden", link_id="link-1")

        assert result == (b"ok", "text/plain")
        assert requests[0].headers["host"] == "evil-alkem.io"
        assert "authorization" not in requests[0].headers

    async def test_relative_uri_never_becomes_credentialed_request(self):
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        with _patch_transport(lambda request: requests.append(request) or httpx.Response(200)):
            result = await client.fetch_url("/api/private/forbidden", link_id="link-1")

        assert result is None
        assert client.last_fetch_refusal is RefusalCategory.SCHEME
        assert requests == []

    async def test_only_deployment_host_receives_credentials_across_redirects(self, monkeypatch: pytest.MonkeyPatch):
        _patch_resolver(
            monkeypatch,
            {
                "deployment.example": ["10.0.0.10"],
                "outside.example": [PUBLIC_ADDRESS],
            },
        )
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.headers["host"] == "deployment.example":
                return httpx.Response(302, headers={"location": "https://outside.example/public.txt"})
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"outside")

        with _patch_transport(handler):
            result = await client.fetch_url("https://deployment.example/initial", link_id="link-1")

        assert result == (b"outside", "text/plain")
        assert requests[0].headers["authorization"] == "Bearer token-123"
        assert "authorization" not in requests[1].headers

    async def test_legitimate_storage_uri_is_rewritten_and_credentialed(self, monkeypatch: pytest.MonkeyPatch):
        _patch_resolver(monkeypatch, {"deployment.example": ["10.0.0.10"]})
        client = _make_client()
        client._session_token = "token-123"
        requests: list[httpx.Request] = []

        with _patch_transport(lambda request: requests.append(request) or httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"storage pdf")):
            result = await client.fetch_url(
                "https://alkem.io/api/private/rest/storage/document/document-id",
                link_id="link-1",
            )

        assert result == (b"storage pdf", "application/pdf")
        assert requests[0].headers["host"] == "deployment.example"
        assert requests[0].headers["authorization"] == "Bearer token-123"

    def test_refusal_records_are_safe_and_auditable(self, caplog: pytest.LogCaptureFixture):
        client = _make_client()
        sentinel = "member-authored-sentinel"
        caplog.set_level("INFO", logger="plugins.ingest_space.graphql_client")

        for category in RefusalCategory:
            client._refuse(
                category,
                link_id="link-123",
                target=f"https://safe.example/{sentinel}?query={sentinel}#{sentinel}",
            )

        text = caplog.text
        assert "link-123" in text
        assert sentinel not in text
        records = [
            record for record in caplog.records
            if record.getMessage().startswith("Link fetch refused:")
        ]
        assert {record.refusal_category for record in records} == {
            category.value for category in RefusalCategory
        }
        assert all(record.link_id == "link-123" for record in records)
        assert all(record.scheme == "https" and record.host == "safe.example" for record in records)
        for category in RefusalCategory:
            assert f"category={category.value}" in text
