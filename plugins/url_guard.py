"""Shared destination validation for outbound URL fetches.

The guard deliberately keeps address classification separate from the HTTP
clients which consume it.  That makes the policy reusable and keeps it inside
the coverage-measured ``plugins`` package.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import zlib
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


RESOLUTION_TIMEOUT_SECONDS = 5.0
_ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_STREAM_CHUNK_BYTES = 64 * 1024
_SNIFF_WINDOW_BYTES = 4 * 1024


class RefusalCategory(str, Enum):
    """Closed set of reasons an outbound fetch may be refused."""

    SCHEME = "scheme"
    DESTINATION = "destination"
    REDIRECT = "redirect"
    HOP_LIMIT = "hop_limit"
    RESOLUTION = "resolution"
    SIZE = "size"
    CONTENT_TYPE = "content_type"
    TRANSPORT = "transport"


@dataclass(frozen=True)
class FetchDecision:
    """The validation outcome for one absolute URL."""

    allowed: bool
    reason: RefusalCategory | None
    address: str | None
    host: str
    is_deployment_host: bool


@dataclass(frozen=True)
class GuardedFetchResult:
    """The outcome of a redirect-aware, pinned outbound HTTP fetch."""

    body: bytes | None
    content_type: str
    url: str
    status_code: int | None
    reason: RefusalCategory | None
    host: str
    hops: int
    error_type: str | None = None


ContentTypePolicy = Callable[[str, bytes | None], bool | None]
HeadersForRequest = Callable[[str, FetchDecision], Awaitable[dict[str, str]]]
RedirectPolicy = Callable[[str], bool]
AsyncClientFactory = Callable[..., httpx.AsyncClient]


async def resolve_host(host: str) -> list[str]:
    """Resolve *host* without blocking the event loop.

    This module-level seam is intentionally the only DNS access point so
    callers and tests can replace it without affecting the system resolver.
    """
    results = await asyncio.to_thread(
        socket.getaddrinfo,
        host,
        None,
        socket.AF_UNSPEC,
        socket.SOCK_STREAM,
    )
    return [str(result[4][0]) for result in results]


def _normalise_host(value: str | None) -> str:
    """Return a lowercased hostname with a port stripped, or an empty string."""
    if not value:
        return ""
    raw_value = value.strip()
    try:
        # A parsed IPv6 hostname has no brackets.  Parse it directly before
        # treating a colon as a URL port separator.
        return str(ipaddress.ip_address(raw_value)).lower()
    except ValueError:
        pass
    try:
        parts = urlsplit(raw_value if "://" in raw_value else f"//{raw_value}")
        return (parts.hostname or "").lower()
    except (TypeError, ValueError):
        return ""


def is_deployment_host(host: str | None, deployment_host: str | None) -> bool:
    """Match the configured deployment by exact, normalised host equality."""
    candidate = _normalise_host(host)
    configured = _normalise_host(deployment_host)
    return bool(candidate and configured and candidate == configured)


def _normalise_origin(value: str | None) -> tuple[str, str, int] | None:
    """Return a comparable HTTP(S) origin, including its effective port."""
    if not value:
        return None
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        if scheme not in _ALLOWED_SCHEMES or not host:
            return None
        port = parts.port
    except (TypeError, ValueError):
        return None
    effective_port = port if port is not None else (443 if scheme == "https" else 80)
    return scheme, host, effective_port


def is_deployment_url(url: str | None, deployment_url: str | None) -> bool:
    """Match the deployment by exact scheme, host, and effective port."""
    candidate = _normalise_origin(url)
    configured = _normalise_origin(deployment_url)
    return bool(candidate and configured and candidate == configured)


def is_platform_domain(host: str | None, platform_domain: str | None) -> bool:
    """Return whether *host* is a platform domain or one of its subdomains."""
    candidate = _normalise_host(host)
    domain = _normalise_host(platform_domain)
    return bool(candidate and domain and (candidate == domain or candidate.endswith(f".{domain}")))


def _literal_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse a literal address, including legacy IPv4 spellings httpx accepts."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        try:
            # ``inet_aton`` understands decimal, octal, and abbreviated IPv4
            # forms accepted by common HTTP stacks.  Judge their canonical
            # destination rather than falling through to DNS.
            address = ipaddress.ip_address(socket.inet_aton(value))
        except (OSError, ValueError):
            return None

    if isinstance(address, ipaddress.IPv6Address):
        mapped_address = address.ipv4_mapped
        if mapped_address is not None:
            return mapped_address
    return address


def _is_denied_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
        or not address.is_global
    )


def _refusal(
    reason: RefusalCategory,
    *,
    host: str = "",
    deployment_host: str | None = None,
    deployment_url: str | None = None,
    url: str | None = None,
) -> FetchDecision:
    return FetchDecision(
        allowed=False,
        reason=reason,
        address=None,
        host=host,
        is_deployment_host=(
            is_deployment_url(url, deployment_url)
            if deployment_url is not None
            else is_deployment_host(host, deployment_host)
        ),
    )


async def check_destination(
    url: str,
    *,
    deployment_host: str | None = None,
    deployment_url: str | None = None,
) -> FetchDecision:
    """Classify one candidate destination without raising for bad input."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        try:
            host = (parts.hostname or "").lower()
        except ValueError:
            return _refusal(
                RefusalCategory.DESTINATION,
                deployment_host=deployment_host,
                deployment_url=deployment_url,
                url=url,
            )

        if scheme not in _ALLOWED_SCHEMES:
            return _refusal(
                RefusalCategory.SCHEME,
                host=host,
                deployment_host=deployment_host,
                deployment_url=deployment_url,
                url=url,
            )
        if not host:
            return _refusal(
                RefusalCategory.DESTINATION,
                deployment_host=deployment_host,
                deployment_url=deployment_url,
                url=url,
            )

        deployment_target = (
            is_deployment_url(url, deployment_url)
            if deployment_url is not None
            else is_deployment_host(host, deployment_host)
        )
        literal = _literal_address(host)
        if literal is not None:
            if not deployment_target and _is_denied_address(literal):
                return _refusal(
                    RefusalCategory.DESTINATION,
                    host=host,
                    deployment_host=deployment_host,
                    deployment_url=deployment_url,
                    url=url,
                )
            return FetchDecision(True, None, str(literal), host, deployment_target)

        try:
            resolved = await asyncio.wait_for(
                resolve_host(host), timeout=RESOLUTION_TIMEOUT_SECONDS,
            )
        except (asyncio.TimeoutError, OSError, ValueError):
            return _refusal(
                RefusalCategory.RESOLUTION,
                host=host,
                deployment_host=deployment_host,
                deployment_url=deployment_url,
                url=url,
            )
        except Exception:
            # A resolver is an I/O boundary: unexpected resolver failures are
            # still a refusal, never an ingest-run failure.
            return _refusal(
                RefusalCategory.RESOLUTION,
                host=host,
                deployment_host=deployment_host,
                deployment_url=deployment_url,
                url=url,
            )

        if not resolved:
            return _refusal(
                RefusalCategory.RESOLUTION,
                host=host,
                deployment_host=deployment_host,
                deployment_url=deployment_url,
                url=url,
            )

        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for value in resolved:
            address = _literal_address(value)
            if address is None:
                return _refusal(
                    RefusalCategory.RESOLUTION,
                    host=host,
                    deployment_host=deployment_host,
                    deployment_url=deployment_url,
                    url=url,
                )
            if not deployment_target and _is_denied_address(address):
                return _refusal(
                    RefusalCategory.DESTINATION,
                    host=host,
                    deployment_host=deployment_host,
                    deployment_url=deployment_url,
                    url=url,
                )
            addresses.append(address)

        return FetchDecision(
            True,
            None,
            str(addresses[0]),
            host,
            deployment_target,
        )
    except (TypeError, ValueError):
        return _refusal(
            RefusalCategory.DESTINATION,
            deployment_host=deployment_host,
            deployment_url=deployment_url,
            url=url,
        )
    except Exception:
        return _refusal(
            RefusalCategory.RESOLUTION,
            deployment_host=deployment_host,
            deployment_url=deployment_url,
            url=url,
        )


def _pinned_target(target: str, address: str | None) -> str:
    """Replace a URL authority with the already-validated connect address."""
    if not address:
        return target
    parts = urlsplit(target)
    address_host = f"[{address}]" if ":" in address else address
    netloc = address_host if parts.port is None else f"{address_host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _host_header(target: str) -> str:
    """Build the logical Host header for a request pinned to an address."""
    parts = urlsplit(target)
    host = parts.hostname or ""
    rendered_host = f"[{host}]" if ":" in host else host
    return rendered_host if parts.port is None else f"{rendered_host}:{parts.port}"


def _redirect_target(response: httpx.Response, current_target: str) -> str | None:
    """Return an absolute HTTP(S) redirect location, or ``None``."""
    location = response.headers.get("location")
    if not location:
        return None
    target = urljoin(current_target, location)
    try:
        parts = urlsplit(target)
        if parts.scheme.lower() not in _ALLOWED_SCHEMES or not parts.hostname:
            return None
    except (TypeError, ValueError):
        return None
    return target


def _content_type(response: httpx.Response) -> str:
    return (response.headers.get("content-type", "") or "").split(";", 1)[0].strip().lower()


def _declares_oversize(response: httpx.Response, max_bytes: int) -> bool:
    declared = response.headers.get("content-length")
    if declared is None:
        return False
    try:
        return int(declared) > max_bytes
    except ValueError:
        return False


class _BoundedContentDecoder:
    """Decode a single HTTP content encoding without materialising a bomb."""

    def __init__(self, content_encoding: str) -> None:
        encoding = content_encoding.strip().lower()
        if encoding in {"", "identity"}:
            self._decompressor: Any | None = None
        elif encoding == "gzip":
            self._decompressor = zlib.decompressobj(zlib.MAX_WBITS | 16)
        elif encoding == "deflate":
            self._decompressor = zlib.decompressobj()
        else:
            raise ValueError(f"unsupported content encoding: {encoding}")

    def decode(self, data: bytes, max_output: int) -> tuple[bytes, bytes]:
        """Return at most ``max_output + 1`` bytes plus unconsumed input."""
        if self._decompressor is None:
            return data[:max_output + 1], data[max_output + 1:]
        decoded = self._decompressor.decompress(data, max_output + 1)
        return decoded, self._decompressor.unconsumed_tail

    def flush(self, max_output: int) -> bytes:
        """Flush the decoder with the same one-byte-over-limit bound."""
        if self._decompressor is None:
            return b""
        return self._decompressor.flush(max_output + 1)


async def _iter_raw_chunks(response: httpx.Response, chunk_size: int):
    """Yield bounded raw chunks, including preloaded MockTransport responses."""
    if hasattr(response, "_content"):
        content = response.content
        for offset in range(0, len(content), chunk_size):
            yield content[offset:offset + chunk_size]
        return
    async for raw_chunk in response.aiter_raw():
        yield raw_chunk


async def _read_bounded_body(
    response: httpx.Response,
    *,
    max_bytes: int,
    content_type: str,
    content_type_policy: ContentTypePolicy | None,
) -> tuple[bytes | None, RefusalCategory | None]:
    """Read raw bytes, enforcing both raw and decoded limits while streaming."""
    def allow_content_type(_: str, __: bytes | None) -> bool:
        return True

    policy = content_type_policy or allow_content_type
    policy_decision = policy(content_type, None)
    if policy_decision is False:
        return None, RefusalCategory.CONTENT_TYPE

    needs_sniff = policy_decision is None
    sniff = bytearray()
    body = bytearray()
    raw_bytes = 0
    # MockTransport eagerly loads ``content=`` responses, which means httpx
    # has already decoded their content before this executor sees it.  Real
    # streamed responses stay raw and are decoded by the bounded decoder.
    content_encoding = (
        ""
        if hasattr(response, "_content") and response.is_stream_consumed
        else response.headers.get("content-encoding", "")
    )
    decoder = _BoundedContentDecoder(content_encoding)

    chunk_size = min(_STREAM_CHUNK_BYTES, max_bytes + 1)
    async for raw_chunk in _iter_raw_chunks(response, chunk_size):
        raw_bytes += len(raw_chunk)
        if raw_bytes > max_bytes:
            return None, RefusalCategory.SIZE

        pending = raw_chunk
        while pending:
            remaining = max_bytes - len(body)
            decode_limit = remaining
            if needs_sniff:
                decode_limit = min(decode_limit, _SNIFF_WINDOW_BYTES - len(sniff))
            decoded, pending = decoder.decode(pending, decode_limit)
            if len(decoded) > decode_limit:
                return None, RefusalCategory.SIZE
            body.extend(decoded)

            if needs_sniff:
                sniff.extend(decoded)
                if len(sniff) >= _SNIFF_WINDOW_BYTES:
                    policy_decision = policy(content_type, bytes(sniff))
                    if policy_decision is not True:
                        return None, RefusalCategory.CONTENT_TYPE
                    needs_sniff = False

    remaining = max_bytes - len(body)
    flushed = decoder.flush(remaining)
    if len(flushed) > remaining:
        return None, RefusalCategory.SIZE
    body.extend(flushed)
    if needs_sniff:
        sniff.extend(flushed[:_SNIFF_WINDOW_BYTES - len(sniff)])
        policy_decision = policy(content_type, bytes(sniff))
        if policy_decision is not True:
            return None, RefusalCategory.CONTENT_TYPE
    return bytes(body), None


@asynccontextmanager
async def _guarded_client(
    client: httpx.AsyncClient | None,
    client_factory: AsyncClientFactory,
):
    """Use a supplied client without owning it, otherwise make a safe one."""
    if client is not None:
        yield client
        return
    async with client_factory(
        timeout=60.0,
        follow_redirects=False,
        limits=httpx.Limits(max_keepalive_connections=0),
    ) as managed_client:
        yield managed_client


async def guarded_fetch(
    url: str,
    *,
    max_bytes: int,
    deployment_url: str | None = None,
    headers_for_request: HeadersForRequest | None = None,
    request_headers: dict[str, str] | None = None,
    content_type_policy: ContentTypePolicy | None = None,
    redirect_policy: RedirectPolicy | None = None,
    client: httpx.AsyncClient | None = None,
    client_factory: AsyncClientFactory = httpx.AsyncClient,
) -> GuardedFetchResult:
    """Fetch an HTTP resource through per-hop validation and address pinning.

    Connections have no keep-alive capacity, so a TLS session opened for one
    redirect hostname can never be reused for another hostname sharing an IP.
    """
    target = url
    redirects_followed = 0
    try:
        async with _guarded_client(client, client_factory) as active_client:
            while True:
                decision = await check_destination(target, deployment_url=deployment_url)
                if not decision.allowed:
                    reason = decision.reason or RefusalCategory.TRANSPORT
                    if redirects_followed and reason is RefusalCategory.DESTINATION:
                        reason = RefusalCategory.REDIRECT
                    return GuardedFetchResult(
                        None,
                        "",
                        target,
                        None,
                        reason,
                        decision.host,
                        redirects_followed,
                    )

                headers = dict(request_headers or {})
                if headers_for_request:
                    headers.update(await headers_for_request(target, decision))
                headers["Host"] = _host_header(target)

                async with active_client.stream(
                    "GET",
                    _pinned_target(target, decision.address),
                    headers=headers,
                    extensions={"sni_hostname": decision.host},
                    follow_redirects=False,
                ) as response:
                    if response.status_code in _REDIRECT_STATUSES:
                        redirect_target = _redirect_target(response, target)
                        if redirect_target is None or (
                            redirect_policy is not None and not redirect_policy(redirect_target)
                        ):
                            return GuardedFetchResult(
                                None,
                                "",
                                target,
                                response.status_code,
                                RefusalCategory.REDIRECT,
                                decision.host,
                                redirects_followed,
                            )
                        if redirects_followed >= MAX_REDIRECT_HOPS:
                            return GuardedFetchResult(
                                None,
                                "",
                                redirect_target,
                                response.status_code,
                                RefusalCategory.HOP_LIMIT,
                                decision.host,
                                redirects_followed,
                            )
                        target = redirect_target
                        redirects_followed += 1
                        continue

                    if response.status_code != 200:
                        return GuardedFetchResult(
                            None,
                            "",
                            target,
                            response.status_code,
                            RefusalCategory.TRANSPORT,
                            decision.host,
                            redirects_followed,
                        )

                    content_type = _content_type(response)
                    if _declares_oversize(response, max_bytes):
                        return GuardedFetchResult(
                            None,
                            content_type,
                            target,
                            response.status_code,
                            RefusalCategory.SIZE,
                            decision.host,
                            redirects_followed,
                        )
                    body, reason = await _read_bounded_body(
                        response,
                        max_bytes=max_bytes,
                        content_type=content_type,
                        content_type_policy=content_type_policy,
                    )
                    return GuardedFetchResult(
                        body,
                        content_type,
                        target,
                        response.status_code,
                        reason,
                        decision.host,
                        redirects_followed,
                    )
    except Exception as exc:
        return GuardedFetchResult(
            None,
            "",
            target,
            None,
            RefusalCategory.TRANSPORT,
            "",
            redirects_followed,
            type(exc).__name__,
        )
