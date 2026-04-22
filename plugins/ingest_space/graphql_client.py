"""GraphQL client with Kratos authentication for the Alkemio private API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


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

    def _rewrite_alkemio_uri(self, url: str) -> str:
        """Point known Alkemio storage URIs at the configured host.

        Seed data often carries prod-shaped URIs (e.g.
        ``https://alkem.io/api/private/rest/storage/document/<id>``) even
        on dev installations.  If the URI path looks like an Alkemio
        internal API call, swap in our deployment's scheme+host.
        """
        if not url:
            return url
        parts = urlsplit(url)
        path = parts.path or ""
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
    ) -> tuple[bytes, str] | None:
        """Fetch an arbitrary URL using the authenticated session.

        Returns ``(body, content_type)`` on success or ``None`` if the
        fetch fails, the content is too large, or auth fails.  Never
        raises — callers keep ingesting other documents.
        """
        if not self._session_token:
            try:
                await self.authenticate()
            except Exception as exc:
                logger.warning("Authentication failed for URL fetch: %s", exc)
                return None

        target = self._rewrite_alkemio_uri(url)
        try:
            async with httpx.AsyncClient(
                timeout=60.0, follow_redirects=True,
            ) as client:
                resp = await client.get(
                    target,
                    headers={
                        "Authorization": f"Bearer {self._session_token}",
                    },
                )
                if resp.status_code != 200:
                    logger.info(
                        "Link fetch returned %d for %s", resp.status_code, target,
                    )
                    return None
                content_type = (
                    resp.headers.get("content-type", "") or ""
                ).split(";")[0].strip().lower()
                body = resp.content
                if len(body) > max_bytes:
                    logger.info(
                        "Link body too large (%d bytes) for %s — skipping",
                        len(body), target,
                    )
                    return None
                return body, content_type
        except Exception as exc:
            logger.warning("Failed to fetch %s: %s", target, exc)
            return None

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
