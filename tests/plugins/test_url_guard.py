"""Unit tests for the shared outbound destination guard."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from plugins import url_guard
from plugins.url_guard import RefusalCategory, check_destination, guarded_fetch


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://example.com", "ftp://example.com", "data:text/plain,hello"])
async def test_disallowed_schemes_do_not_resolve(url: str, monkeypatch: pytest.MonkeyPatch):
    resolver = AsyncMock()
    monkeypatch.setattr(url_guard, "resolve_host", resolver)

    decision = await check_destination(url)

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.SCHEME
    resolver.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.42.42/",
        "http://169.254.0.0/",
        "http://169.254.255.255/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.0.0.0/",
        "http://10.255.255.255/",
        "http://172.16.0.0/",
        "http://172.31.255.255/",
        "http://192.168.0.0/",
        "http://192.168.255.255/",
        "http://2130706433/",
        "http://0177.0.0.1/",
        "http://[::ffff:127.0.0.1]/",
    ],
)
async def test_denied_literal_addresses(url: str):
    decision = await check_destination(url)

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.DESTINATION


async def test_public_literal_address_is_allowed():
    decision = await check_destination("https://93.184.216.34/document.pdf")

    assert decision.allowed is True
    assert decision.reason is None
    assert decision.address == "93.184.216.34"


async def test_hostname_with_any_private_result_is_denied(monkeypatch: pytest.MonkeyPatch):
    async def resolve_host(_: str) -> list[str]:
        return ["93.184.216.34", "10.0.0.1"]

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)

    decision = await check_destination("https://mixed.example/document.pdf")

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.DESTINATION


async def test_hostname_with_only_public_results_is_allowed(monkeypatch: pytest.MonkeyPatch):
    async def resolve_host(_: str) -> list[str]:
        return ["93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"]

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)

    decision = await check_destination("https://public.example/document.pdf")

    assert decision.allowed is True
    assert decision.address == "93.184.216.34"


async def test_hostname_resolving_private_is_denied(monkeypatch: pytest.MonkeyPatch):
    async def resolve_host(_: str) -> list[str]:
        return ["192.168.1.10"]

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)

    decision = await check_destination("https://looks-public.example/document.pdf")

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.DESTINATION


async def test_empty_host_is_denied():
    decision = await check_destination("https:///path")

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.DESTINATION


async def test_empty_resolution_is_refused(monkeypatch: pytest.MonkeyPatch):
    async def resolve_host(_: str) -> list[str]:
        return []

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)

    decision = await check_destination("https://empty.example/document.pdf")

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.RESOLUTION


async def test_deployment_host_bypasses_only_address_classification(monkeypatch: pytest.MonkeyPatch):
    resolver = AsyncMock(return_value=["10.0.0.15"])
    monkeypatch.setattr(url_guard, "resolve_host", resolver)

    allowed = await check_destination(
        "http://deployment.internal/document.pdf",
        deployment_host="deployment.internal",
    )
    rejected = await check_destination(
        "ftp://deployment.internal/document.pdf",
        deployment_host="deployment.internal",
    )

    assert allowed.allowed is True
    assert allowed.is_deployment_host is True
    assert allowed.address == "10.0.0.15"
    assert rejected.allowed is False
    assert rejected.reason is RefusalCategory.SCHEME
    assert resolver.await_count == 1


async def test_resolution_failure_is_refused(monkeypatch: pytest.MonkeyPatch):
    async def resolve_host(_: str) -> list[str]:
        raise socket.gaierror("not found")

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)

    decision = await check_destination("https://missing.example/document.pdf")

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.RESOLUTION


async def test_resolution_timeout_is_refused(monkeypatch: pytest.MonkeyPatch):
    async def resolve_host(_: str) -> list[str]:
        await asyncio.Event().wait()
        return []

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)
    monkeypatch.setattr(url_guard, "RESOLUTION_TIMEOUT_SECONDS", 0.01)

    decision = await check_destination("https://slow.example/document.pdf")

    assert decision.allowed is False
    assert decision.reason is RefusalCategory.RESOLUTION


def test_host_helpers_only_match_real_domain_boundaries():
    assert url_guard.is_platform_domain("alkem.io", "alkem.io")
    assert url_guard.is_platform_domain("storage.alkem.io", "alkem.io")
    assert not url_guard.is_platform_domain("evil-alkem.io", "alkem.io")
    assert url_guard.is_deployment_host("DEV.alkemio.org:443", "dev.alkemio.org")
    assert not url_guard.is_deployment_host("dev.alkemio.org.evil.example", "dev.alkemio.org")
    assert not url_guard.is_deployment_host("evil-deployment.example", "deployment.example")


async def test_deployment_origin_requires_matching_scheme_host_and_port(
    monkeypatch: pytest.MonkeyPatch,
):
    async def resolve_host(_: str) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(url_guard, "resolve_host", resolve_host)

    allowed = await check_destination(
        "http://localhost:3000/document.pdf",
        deployment_url="http://localhost:3000/api/private/graphql",
    )
    alternate_port = await check_destination(
        "http://localhost:8080/document.pdf",
        deployment_url="http://localhost:3000/api/private/graphql",
    )
    alternate_scheme = await check_destination(
        "https://localhost:3000/document.pdf",
        deployment_url="http://localhost:3000/api/private/graphql",
    )

    assert allowed.is_deployment_host is True
    assert alternate_port.is_deployment_host is False
    assert alternate_scheme.is_deployment_host is False


async def test_guarded_fetch_disables_connection_reuse_across_hops():
    captured_limits: list[httpx.Limits] = []
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"ok")
    )

    def client_factory(**kwargs) -> httpx.AsyncClient:
        captured_limits.append(kwargs["limits"])
        return httpx.AsyncClient(transport=transport)

    result = await guarded_fetch(
        "https://93.184.216.34/document.txt",
        max_bytes=1024,
        client_factory=client_factory,
    )

    assert result.body == b"ok"
    assert captured_limits[0].max_keepalive_connections == 0
