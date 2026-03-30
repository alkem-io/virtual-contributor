"""GraphQL client with Kratos authentication for the Alkemio private API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
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
