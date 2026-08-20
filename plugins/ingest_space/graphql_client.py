"""GraphQL client with Kratos authentication for the Alkemio private API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from plugins.ingest_space.link_extractor import _MIME_KIND, _detect_kind
from plugins.url_guard import (
    FetchDecision,
    MAX_REDIRECT_HOPS as _MAX_REDIRECT_HOPS,
    RefusalCategory,
    guarded_fetch,
    is_deployment_url,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0
MAX_REDIRECT_HOPS = _MAX_REDIRECT_HOPS


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
        self.last_fetch_refusal: RefusalCategory | None = None

    def _rewrite_alkemio_uri(self, url: str) -> str:
        """Point known Alkemio storage URIs at the configured host.

        Seed data often carries prod-shaped URIs (e.g.
        ``https://alkem.io/api/private/rest/storage/document/<id>``) even
        on dev installations.  If the URI path looks like an Alkemio
        internal API call, swap in our deployment's scheme+host.

        Only rewrites the exact ``alkem.io`` apex or configured deployment.
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
        if host != "alkem.io" and not is_deployment_url(url, self._graphql_endpoint):
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
        result = await guarded_fetch(
            target,
            max_bytes=max_bytes,
            deployment_url=self._graphql_endpoint,
            headers_for_request=self._headers_for_request,
            content_type_policy=self._content_type_policy,
            client_factory=httpx.AsyncClient,
        )
        if result.body is None:
            self._refuse(
                result.reason or RefusalCategory.TRANSPORT,
                link_id=link_id,
                target=result.url,
                host=result.host,
                hops=result.hops,
                error_type=result.error_type,
            )
            return None
        return result.body, result.content_type

    async def _headers_for_request(
        self,
        _target: str,
        decision: FetchDecision,
    ) -> dict[str, str]:
        """Build per-hop headers after the shared executor validates the origin."""
        if not self._session_token:
            await self.authenticate()

        headers: dict[str, str] = {}
        if decision.is_deployment_host and self._session_token:
            headers["Authorization"] = f"Bearer {self._session_token}"
        return headers

    @staticmethod
    def _is_supported_content_type(content_type: str) -> bool:
        return any(token in content_type for token in _MIME_KIND)

    @staticmethod
    def _content_type_policy(content_type: str, sniff: bytes | None) -> bool | None:
        """Accept known extractable types; sniff only unrecognised headers."""
        if GraphQLClient._is_supported_content_type(content_type):
            return True
        if content_type.startswith(("image/", "audio/", "video/", "font/")):
            return False
        if sniff is None:
            return None
        return _detect_kind(sniff, content_type) is not None

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
