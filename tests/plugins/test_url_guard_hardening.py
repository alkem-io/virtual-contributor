"""Regression tests for guard-owned outbound HTTP request properties."""

from __future__ import annotations

import gzip

import httpx
import pytest

from plugins import url_guard
from plugins.url_guard import guarded_fetch


def _patch_guard_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler,
) -> None:
    """Route the guard-owned client through an in-process transport."""
    client_class = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def guarded_client(**kwargs) -> httpx.AsyncClient:
        return client_class(transport=transport, **kwargs)

    monkeypatch.setattr(url_guard.httpx, "AsyncClient", guarded_client)


class ChunkedStream(httpx.AsyncByteStream):
    """A raw response stream whose chunk boundaries are controlled by the test."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.iterated = False

    async def __aiter__(self):
        self.iterated = True
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


@pytest.mark.parametrize("header_name", ["accept-encoding", "Accept-Encoding", "ACCEPT-ENCODING"])
@pytest.mark.parametrize("source", ["request_headers", "headers_for_request"])
async def test_guard_owns_accept_encoding_regardless_of_caller_header_casing(
    header_name: str,
    source: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """Caller casing must not turn the supported encoding list into a union."""
    requests: list[httpx.Request] = []
    _patch_guard_transport(
        monkeypatch,
        lambda request: requests.append(request) or httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"ok",
        ),
    )

    if source == "request_headers":
        result = await guarded_fetch(
            "https://93.184.216.34/document.txt",
            max_bytes=1024,
            request_headers={header_name: "zstd"},
        )
    else:
        async def headers_for_request(_: str, __: url_guard.FetchDecision) -> dict[str, str]:
            return {header_name: "zstd"}

        result = await guarded_fetch(
            "https://93.184.216.34/document.txt",
            max_bytes=1024,
            headers_for_request=headers_for_request,
        )

    assert result.body == b"ok"
    assert requests[0].headers["accept-encoding"] == "gzip, deflate"


async def test_guard_owns_host_regardless_of_caller_header_casing(
    monkeypatch: pytest.MonkeyPatch,
):
    """The validated virtual-host authority must be the only Host header."""
    requests: list[httpx.Request] = []
    _patch_guard_transport(
        monkeypatch,
        lambda request: requests.append(request) or httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"ok",
        ),
    )

    async def resolve_host(host: str) -> list[str]:
        assert host == "public.example"
        return ["93.184.216.34"]

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)
    result = await guarded_fetch(
        "https://public.example/document.txt",
        max_bytes=1024,
        request_headers={
            "host": "attacker-one.example",
            "Host": "attacker-two.example",
            "HOST": "attacker-three.example",
        },
    )

    assert result.body == b"ok"
    assert requests[0].headers.get_list("host") == ["public.example"]


async def test_guarded_fetch_refuses_streamed_gzip_expansion_over_cap(
    monkeypatch: pytest.MonkeyPatch,
):
    """The bounded decoder applies the decoded limit to raw streamed gzip."""
    compressed = gzip.compress(b"x" * 2048)
    stream = ChunkedStream([compressed])
    _patch_guard_transport(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            headers={"content-encoding": "gzip", "content-type": "text/plain"},
            stream=stream,
        ),
    )

    result = await guarded_fetch("https://93.184.216.34/document.txt", max_bytes=1024)

    assert result.body is None
    assert result.reason is url_guard.RefusalCategory.SIZE
    assert stream.iterated


async def test_guarded_fetch_decodes_streamed_gzip_across_chunk_boundaries(
    monkeypatch: pytest.MonkeyPatch,
):
    """Raw gzip decoding has the same successful result in one or many chunks."""
    body = b"a legitimate compressed response" * 8
    compressed = gzip.compress(body)
    single_chunk = ChunkedStream([compressed])
    several_chunks = ChunkedStream([compressed[:3], compressed[3:11], compressed[11:]])
    streams = iter([single_chunk, several_chunks])
    _patch_guard_transport(
        monkeypatch,
        lambda _: httpx.Response(
            200,
            headers={"content-encoding": "gzip", "content-type": "text/plain"},
            stream=next(streams),
        ),
    )

    one_chunk = await guarded_fetch("https://93.184.216.34/document.txt", max_bytes=1024)
    multiple_chunks = await guarded_fetch("https://93.184.216.34/document.txt", max_bytes=1024)

    assert one_chunk == multiple_chunks
    assert one_chunk.body == body
    assert one_chunk.reason is None
    assert single_chunk.iterated
    assert several_chunks.iterated


async def test_guard_owns_credentials_on_public_hops(
    monkeypatch: pytest.MonkeyPatch,
):
    """Only the guard-approved bearer reaches its matching deployment hop."""
    requests: list[httpx.Request] = []
    deployment_url = "https://93.184.216.34/api/private/graphql"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers["host"] == "93.184.216.34" and request.url.path == "/initial":
            return httpx.Response(302, headers={"location": "https://1.1.1.1/public.txt"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    _patch_guard_transport(monkeypatch, handler)
    public_result = await guarded_fetch(
        "https://1.1.1.1/document.txt",
        max_bytes=1024,
        deployment_url=deployment_url,
        credential_token="trusted-token",
    )
    redirect_result = await guarded_fetch(
        "https://93.184.216.34/initial",
        max_bytes=1024,
        deployment_url=deployment_url,
        credential_token="trusted-token",
    )

    assert public_result.body == b"ok"
    assert redirect_result.body == b"ok"
    assert redirect_result.url == "https://1.1.1.1/public.txt"
    assert "authorization" not in requests[0].headers
    assert "proxy-authorization" not in requests[0].headers
    assert requests[1].headers["authorization"] == "Bearer trusted-token"
    assert "proxy-authorization" not in requests[1].headers
    assert "authorization" not in requests[2].headers
    assert "proxy-authorization" not in requests[2].headers


@pytest.mark.parametrize("transport_argument", ["client", "client_factory"])
async def test_guarded_fetch_rejects_caller_controlled_transport(
    transport_argument: str,
):
    """The public fetch API cannot receive a caller-created transport."""
    with pytest.raises(TypeError, match=f"unexpected keyword argument '{transport_argument}'"):
        await guarded_fetch(
            "https://1.1.1.1/document.txt",
            max_bytes=1024,
            **{transport_argument: object()},
        )


async def test_guard_client_ignores_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
):
    """Proxy and CA environment variables cannot redirect a pinned request.

    httpx trusts the environment by default, so HTTP_PROXY/HTTPS_PROXY/ALL_PROXY
    would install proxy mounts that route around the address the guard resolved,
    validated and pinned — and SSL_CERT_FILE would replace the trust store that
    pinning depends on for hostname verification.
    """
    for variable in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.setenv(variable, "http://127.0.0.1:9")

    captured: list[httpx.AsyncClient] = []
    client_class = httpx.AsyncClient

    def recording_client(**kwargs) -> httpx.AsyncClient:
        client = client_class(**kwargs)
        captured.append(client)
        return client

    monkeypatch.setattr(url_guard.httpx, "AsyncClient", recording_client)

    async with url_guard._guarded_client():
        pass

    assert captured, "the guard did not construct a client"
    assert captured[0]._mounts == {}, "proxy environment installed transport mounts"
