"""HTTP client for the ESP32 IR-transmitter firmware."""

from __future__ import annotations

from typing import Any

import httpx


class IRNodeError(RuntimeError):
    pass


class IRNode:
    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def send(self, command: dict[str, Any]) -> None:
        """Translate a Flipper-style command dict into the firmware's payload."""
        kind = command.get("type")
        if kind == "parsed":
            payload = {
                "protocol": command["protocol"].upper(),
                "address": command["address"],
                "command": command["command"],
            }
        elif kind == "raw":
            payload = {
                "freq": command["frequency"],
                "raw": command["data"],
            }
        else:
            raise IRNodeError(f"unknown command type: {kind!r}")

        await self._post("/ir", payload)

    async def status(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self._base}/")
            r.raise_for_status()
            return r.json()

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(f"{self._base}/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def _post(self, path: str, payload: dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(f"{self._base}{path}", json=payload)
        except httpx.HTTPError as exc:
            raise IRNodeError(f"node unreachable at {self._base}: {exc}") from exc
        if r.status_code >= 400:
            raise IRNodeError(f"node returned {r.status_code}: {r.text}")
