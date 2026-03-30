from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)

CONTENT_TYPE_JSON = "application/json"


class HealthServer:
    """Lightweight async HTTP health server for Kubernetes probes."""

    def __init__(self, port: int = 8080) -> None:
        self._port = port
        self._server: asyncio.Server | None = None
        self._checks: dict[str, Callable[[], bool]] = {}

    def add_check(self, name: str, check: Callable[[], bool]) -> None:
        """Register a readiness check."""
        self._checks[name] = check

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, "0.0.0.0", self._port
        )
        logger.info("Health server listening on port %d", self._port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Health server stopped")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            data = await asyncio.wait_for(reader.read(4096), timeout=5.0)
            request_line = data.decode().split("\r\n")[0]
            path = request_line.split(" ")[1] if " " in request_line else "/"

            if path == "/healthz":
                await self._send_response(writer, 200, {"status": "ok"})
            elif path == "/readyz":
                await self._handle_readyz(writer)
            else:
                await self._send_response(writer, 404, {"error": "not found"})
        except Exception:
            logger.exception("Health server error")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_readyz(self, writer: asyncio.StreamWriter) -> None:
        checks = {}
        for name, check_fn in self._checks.items():
            try:
                checks[name] = "connected" if check_fn() else "disconnected"
            except Exception:
                checks[name] = "error"

        all_ok = all(v in ("connected", "started") for v in checks.values())
        status_code = 200 if all_ok else 503
        body = {
            "status": "ready" if all_ok else "not_ready",
            "checks": checks,
        }
        await self._send_response(writer, status_code, body)

    async def _send_response(
        self, writer: asyncio.StreamWriter, status: int, body: dict
    ) -> None:
        status_text = "OK" if status == 200 else "Service Unavailable" if status == 503 else "Not Found"
        payload = json.dumps(body)
        response = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: {CONTENT_TYPE_JSON}\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"\r\n"
            f"{payload}"
        )
        writer.write(response.encode())
        await writer.drain()
