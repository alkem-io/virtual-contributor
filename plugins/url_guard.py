"""Shared destination validation for outbound URL fetches.

The guard deliberately keeps address classification separate from the HTTP
clients which consume it.  That makes the policy reusable and keeps it inside
the coverage-measured ``plugins`` package.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit


RESOLUTION_TIMEOUT_SECONDS = 5.0
_ALLOWED_SCHEMES = frozenset({"http", "https"})


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
) -> FetchDecision:
    return FetchDecision(
        allowed=False,
        reason=reason,
        address=None,
        host=host,
        is_deployment_host=is_deployment_host(host, deployment_host),
    )


async def check_destination(
    url: str,
    *,
    deployment_host: str | None = None,
) -> FetchDecision:
    """Classify one candidate destination without raising for bad input."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        try:
            host = (parts.hostname or "").lower()
        except ValueError:
            return _refusal(RefusalCategory.DESTINATION, deployment_host=deployment_host)

        if scheme not in _ALLOWED_SCHEMES:
            return _refusal(
                RefusalCategory.SCHEME,
                host=host,
                deployment_host=deployment_host,
            )
        if not host:
            return _refusal(RefusalCategory.DESTINATION, deployment_host=deployment_host)

        deployment_target = is_deployment_host(host, deployment_host)
        literal = _literal_address(host)
        if literal is not None:
            if not deployment_target and _is_denied_address(literal):
                return _refusal(
                    RefusalCategory.DESTINATION,
                    host=host,
                    deployment_host=deployment_host,
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
            )
        except Exception:
            # A resolver is an I/O boundary: unexpected resolver failures are
            # still a refusal, never an ingest-run failure.
            return _refusal(
                RefusalCategory.RESOLUTION,
                host=host,
                deployment_host=deployment_host,
            )

        if not resolved:
            return _refusal(
                RefusalCategory.RESOLUTION,
                host=host,
                deployment_host=deployment_host,
            )

        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for value in resolved:
            address = _literal_address(value)
            if address is None:
                return _refusal(
                    RefusalCategory.RESOLUTION,
                    host=host,
                    deployment_host=deployment_host,
                )
            if not deployment_target and _is_denied_address(address):
                return _refusal(
                    RefusalCategory.DESTINATION,
                    host=host,
                    deployment_host=deployment_host,
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
        return _refusal(RefusalCategory.DESTINATION, deployment_host=deployment_host)
    except Exception:
        return _refusal(RefusalCategory.RESOLUTION, deployment_host=deployment_host)
