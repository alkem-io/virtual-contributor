"""Regression tests for guard-owned outbound HTTP request properties."""

from __future__ import annotations

import httpx
import pytest

from plugins import url_guard
from plugins.url_guard import guarded_fetch


@pytest.mark.parametrize("header_name", ["accept-encoding", "Accept-Encoding", "ACCEPT-ENCODING"])
@pytest.mark.parametrize("source", ["request_headers", "headers_for_request"])
async def test_guard_owns_accept_encoding_regardless_of_caller_header_casing(
    header_name: str,
    source: str,
):
    """Caller casing must not turn the supported encoding list into a union."""
    requests: list[httpx.Request] = []
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"ok",
            )
        )
    )

    async with client:
        if source == "request_headers":
            result = await guarded_fetch(
                "https://93.184.216.34/document.txt",
                max_bytes=1024,
                request_headers={header_name: "zstd"},
                client=client,
            )
        else:
            async def headers_for_request(_: str, __: url_guard.FetchDecision) -> dict[str, str]:
                return {header_name: "zstd"}

            result = await guarded_fetch(
                "https://93.184.216.34/document.txt",
                max_bytes=1024,
                headers_for_request=headers_for_request,
                client=client,
            )

    assert result.body == b"ok"
    assert requests[0].headers["accept-encoding"] == "gzip, deflate"


async def test_guard_neutralizes_credentials_on_a_preconfigured_supplied_client():
    """Client defaults cannot bypass the guard's per-origin bearer decision."""
    requests: list[httpx.Request] = []
    deployment_url = "https://93.184.216.34/api/private/graphql"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers["host"] == "93.184.216.34" and request.url.path == "/initial":
            return httpx.Response(302, headers={"location": "https://1.1.1.1/public.txt"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer client-default", "Proxy-Authorization": "client-proxy-default"},
        auth=httpx.BasicAuth("client", "secret"),
    ) as client:
        public_result = await guarded_fetch(
            "https://1.1.1.1/document.txt",
            max_bytes=1024,
            deployment_url=deployment_url,
            credential_token="trusted-token",
            client=client,
        )
        redirect_result = await guarded_fetch(
            "https://93.184.216.34/initial",
            max_bytes=1024,
            deployment_url=deployment_url,
            credential_token="trusted-token",
            client=client,
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


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("https://1.1.1.1/document.txt", id="direct-public"),
        pytest.param("https://93.184.216.34/initial", id="deployment-to-public-redirect"),
    ],
)
async def test_guard_rejects_client_request_hooks_before_any_public_hop(target: str):
    """Event hooks run after guard sanitisation, so they cannot be accepted."""
    transport_requests: list[httpx.Request] = []
    hook_requests: list[httpx.Request] = []

    async def sneaky_hook(request: httpx.Request) -> None:
        hook_requests.append(request)
        request.headers["Authorization"] = "Bearer event-hook-secret"
        request.headers["Accept-Encoding"] = "zstd"

    def handler(request: httpx.Request) -> httpx.Response:
        transport_requests.append(request)
        if request.url.path == "/initial":
            return httpx.Response(302, headers={"location": "https://1.1.1.1/public.txt"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        event_hooks={"request": [sneaky_hook]},
    ) as client:
        with pytest.raises(ValueError, match="request event hooks"):
            await guarded_fetch(
                target,
                max_bytes=1024,
                deployment_url="https://93.184.216.34/api/private/graphql",
                credential_token="trusted-token",
                client=client,
            )

    assert hook_requests == []
    assert transport_requests == []
