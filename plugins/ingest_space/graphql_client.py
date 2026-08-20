"""GraphQL client with Kratos authentication for the Alkemio private API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from plugins.ingest_space.link_extractor import _MIME_KIND
from plugins.url_guard import (
    FetchDecision,
    RefusalCategory,
    check_destination,
    is_deployment_host,
    is_platform_domain,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class GraphQLClient:
    """Authenticated GraphQL client for Alkemio's private API."""

    def __init__(
        self,
        graphql_endpoint: str,
        kratos_public_url: str,
        email: str,
        password: str,
    ) -> None:
        self._graphql_endpoint = graphql_endpoint
        self._kratos_public_url = kratos_public_url.rstrip("/")
        self._email = email
        self._password = password
        self._session_token: str | None = None
        # Cache the scheme/host of the GraphQL endpoint so we can rewrite
        # foreign (e.g. production-shaped) Alkemio URIs onto our deployment.
        parts = urlsplit(self._graphql_endpoint)
        self._base_scheme = parts.scheme or "http"
        self._base_netloc = parts.netloc
        self._base_host = (parts.hostname or "").lower()
        self.last_fetch_refusal: RefusalCategory | None = None

    def _rewrite_alkemio_uri(self, url: str) -> str:
        """Point known Alkemio storage URIs at the configured host.

        Seed data often carries prod-shaped URIs (e.g.
        ``https://alkem.io/api/private/rest/storage/document/<id>``) even
        on dev installations.  If the URI path looks like an Alkemio
        internal API call, swap in our deployment's scheme+host.

        Only rewrites a real ``alkem.io`` domain or the configured deployment.
        Host-less relative URLs are never rewritten: a member-supplied relative
        URI must not turn into an authenticated deployment request.
        """
        if not url:
            return url
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
        except (TypeError, ValueError):
            return url
        path = parts.path or ""
        if not host:
            return url
        if not (
            is_platform_domain(host, "alkem.io")
            or is_deployment_host(host, self._base_host)
        ):
            return url
        if path.startswith("/api/") or path.startswith("/rest/"):
            return urlunsplit((
                self._base_scheme,
                self._base_netloc,
                path,
                parts.query,
                parts.fragment,
            ))
        return url

    async def fetch_url(
        self,
        url: str,
        *,
        max_bytes: int = 10 * 1024 * 1024,
        link_id: str | None = None,
    ) -> tuple[bytes, str] | None:
        """Fetch an arbitrary URL using the authenticated session.

        Returns ``(body, content_type)`` on success or ``None`` if the
        fetch fails, the content is too large, or auth fails.  Never
        raises — callers keep ingesting other documents.
        """
        target = self._rewrite_alkemio_uri(url)
        self.last_fetch_refusal = None
        try:
            async with httpx.AsyncClient(
                timeout=60.0, follow_redirects=False,
            ) as client:
                redirects_followed = 0
                while True:
                    decision = await check_destination(
                        target,
                        deployment_host=self._base_host,
                    )
                    if not decision.allowed:
                        category = decision.reason
                        if redirects_followed and category is RefusalCategory.DESTINATION:
                            category = RefusalCategory.REDIRECT
                        self._refuse(
                            category or RefusalCategory.TRANSPORT,
                            link_id=link_id,
                            target=target,
                            host=decision.host,
                            hops=redirects_followed,
                        )
                        return None

                    headers, request_target, extensions = await self._request_details(
                        target,
                        decision,
                        link_id=link_id,
                        hops=redirects_followed,
                    )
                    if headers is None:
                        return None

                    async with client.stream(
                        "GET",
                        request_target,
                        headers=headers,
                        extensions=extensions,
                    ) as response:
                        if response.status_code in _REDIRECT_STATUSES:
                            redirect_target = self._redirect_target(response, target)
                            if redirect_target is None:
                                self._refuse(
                                    RefusalCategory.REDIRECT,
                                    link_id=link_id,
                                    hops=redirects_followed,
                                )
                                return None
                            if redirects_followed >= MAX_REDIRECT_HOPS:
                                self._refuse(
                                    RefusalCategory.HOP_LIMIT,
                                    link_id=link_id,
                                    target=redirect_target,
                                    hops=redirects_followed,
                                )
                                return None
                            target = redirect_target
                            redirects_followed += 1
                            continue

                        if response.status_code != 200:
                            self._refuse(
                                RefusalCategory.TRANSPORT,
                                link_id=link_id,
                                target=target,
                                host=decision.host,
                                hops=redirects_followed,
                            )
                            return None

                        content_type = self._content_type(response)
                        if not self._is_supported_content_type(content_type):
                            self._refuse(
                                RefusalCategory.CONTENT_TYPE,
                                link_id=link_id,
                                target=target,
                                host=decision.host,
                                hops=redirects_followed,
                            )
                            return None
                        if self._declares_oversize(response, max_bytes):
                            self._refuse(
                                RefusalCategory.SIZE,
                                link_id=link_id,
                                target=target,
                                host=decision.host,
                                hops=redirects_followed,
                            )
                            return None

                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > max_bytes:
                                self._refuse(
                                    RefusalCategory.SIZE,
                                    link_id=link_id,
                                    target=target,
                                    host=decision.host,
                                    hops=redirects_followed,
                                )
                                return None
                        return bytes(body), content_type
        except Exception as exc:
            self._refuse(
                RefusalCategory.TRANSPORT,
                link_id=link_id,
                target=target,
                error_type=type(exc).__name__,
            )
            return None

    async def _request_details(
        self,
        target: str,
        decision: FetchDecision,
        *,
        link_id: str | None,
        hops: int,
    ) -> tuple[dict[str, str] | None, str, dict[str, str]]:
        """Build per-hop credentials and the pinned-address request target."""
        if not self._session_token:
            try:
                await self.authenticate()
            except Exception as exc:
                self._refuse(
                    RefusalCategory.TRANSPORT,
                    link_id=link_id,
                    target=target,
                    host=decision.host,
                    hops=hops,
                    error_type=type(exc).__name__,
                )
                return None, target, {}

        headers: dict[str, str] = {}
        if decision.is_deployment_host and self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"

        request_target = self._pinned_target(target, decision.address)
        headers["Host"] = self._host_header(target)
        return headers, request_target, {"sni_hostname": decision.host}

    @staticmethod
    def _pinned_target(target: str, address: str | None) -> str:
        """Replace the authority with a validated literal address for connect."""
        if not address:
            return target
        parts = urlsplit(target)
        address_host = f"[{address}]" if ":" in address else address
        port = parts.port
        netloc = address_host if port is None else f"{address_host}:{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    @staticmethod
    def _host_header(target: str) -> str:
        """Build a Host header for a request whose connection is pinned."""
        parts = urlsplit(target)
        host = parts.hostname or ""
        rendered_host = f"[{host}]" if ":" in host else host
        return rendered_host if parts.port is None else f"{rendered_host}:{parts.port}"

    @staticmethod
    def _redirect_target(response: httpx.Response, current_target: str) -> str | None:
        location = response.headers.get("location")
        if not location:
            return None
        target = urljoin(current_target, location)
        try:
            parts = urlsplit(target)
            if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
                return None
        except (TypeError, ValueError):
            return None
        return target

    @staticmethod
    def _content_type(response: httpx.Response) -> str:
        return (response.headers.get("content-type", "") or "").split(";", 1)[0].strip().lower()

    @staticmethod
    def _is_supported_content_type(content_type: str) -> bool:
        return any(token in content_type for token in _MIME_KIND)

    @staticmethod
    def _declares_oversize(response: httpx.Response, max_bytes: int) -> bool:
        declared = response.headers.get("content-length")
        if declared is None:
            return False
        try:
            return int(declared) > max_bytes
        except ValueError:
            return False

    def _refuse(
        self,
        category: RefusalCategory,
        *,
        link_id: str | None,
        target: str = "",
        host: str = "",
        hops: int = 0,
        error_type: str | None = None,
    ) -> None:
        """Record a fetch refusal without exposing member-authored URL data."""
        self.last_fetch_refusal = category
        scheme = ""
        if target:
            try:
                parts = urlsplit(target)
                scheme = parts.scheme.lower()
                host = host or (parts.hostname or "").lower()
            except (TypeError, ValueError):
                pass
        logger.info(
            "Link fetch refused: link_id=%s category=%s scheme=%s host=%s hops=%d",
            link_id or "",
            category.value,
            scheme,
            host,
            hops,
            extra={
                "link_id": link_id or "",
                "refusal_category": category.value,
                "scheme": scheme,
                "host": host,
                "hops": hops,
            },
        )
        if error_type:
            logger.warning(
                "Link fetch refusal transport detail: link_id=%s error_type=%s",
                link_id or "",
                error_type,
            )

    async def authenticate(self) -> None:
        """Authenticate via Kratos login flow."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Init login flow
            flow_resp = await client.get(
                f"{self._kratos_public_url}/self-service/login/api"
            )
            flow_resp.raise_for_status()
            flow_data = flow_resp.json()
            action_url = flow_data["ui"]["action"]

            # Submit credentials
            login_resp = await client.post(
                action_url,
                json={
                    "method": "password",
                    "identifier": self._email,
                    "password": self._password,
                },
            )
            login_resp.raise_for_status()
            login_data = login_resp.json()
            self._session_token = login_data["session_token"]
            logger.info("Kratos authentication successful")

    async def query(self, query_str: str, variables: dict | None = None) -> dict[str, Any]:
        """Execute a GraphQL query with retry."""
        if not self._session_token:
            await self.authenticate()

        last_exc = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    resp = await client.post(
                        self._graphql_endpoint,
                        headers={
                            "Authorization": f"Bearer {self._session_token}",
                            "Content-Type": "application/json",
                        },
                        json={"query": query_str, "variables": variables or {}},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if "errors" in data:
                        raise RuntimeError(f"GraphQL errors: {data['errors']}")
                    return data.get("data", {})
                except Exception as exc:
                    last_exc = exc
                    if attempt < MAX_RETRIES - 1:
                        delay = BASE_DELAY * (2 ** attempt)
                        logger.warning("GraphQL query attempt %d failed: %s", attempt + 1, exc)
                        await asyncio.sleep(delay)
        raise last_exc
