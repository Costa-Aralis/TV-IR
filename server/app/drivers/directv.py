"""DirecTV receiver HTTP control (Genie / HR-series).

Most DirecTV receivers expose an unauthenticated HTTP API on port 8080
when "External Device: Allow" is enabled in Settings → Whole-Home →
External Device.

Useful endpoints:
  GET  /info/getVersion                      — sanity / probe
  GET  /tv/getTuned                          — what the box is tuned to
  GET  /tv/tune?major=NNN                    — tune to a channel
  GET  /tv/tune?major=N&minor=M              — sub-channels
  GET  /remote/processKey?key=KEY            — simulate a remote key
                                               (e.g. POWER, GUIDE, MENU,
                                               UP, DOWN, ENTER, EXIT, …)

Reference: https://github.com/sentry07/PyDirectv (community RE)
"""

from __future__ import annotations

from typing import Any

import httpx


class DirectvError(RuntimeError):
    pass


class DirectvClient:
    def __init__(self, host: str, *, timeout: float = 5.0, port: int = 8080) -> None:
        self._base = f"http://{host}:{port}".rstrip("/")
        self._timeout = timeout

    async def info(self) -> dict[str, Any]:
        return await self._get("/info/getVersion")

    async def tuned(self) -> dict[str, Any]:
        return await self._get("/tv/getTuned")

    async def tune(self, major: int, minor: int | None = None) -> dict[str, Any]:
        params = {"major": str(major)}
        if minor is not None:
            params["minor"] = str(minor)
        return await self._get("/tv/tune", params=params)

    async def keypress(self, key: str) -> dict[str, Any]:
        return await self._get("/remote/processKey", params={"key": key, "hold": "keyPress"})

    async def healthy(self) -> bool:
        try:
            await self.info()
            return True
        except DirectvError:
            return False

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(f"{self._base}{path}", params=params)
        except httpx.HTTPError as exc:
            raise DirectvError(f"directv unreachable {self._base}: {exc}") from exc
        if r.status_code >= 400:
            raise DirectvError(f"directv {r.status_code}: {r.text}")
        try:
            return r.json()
        except ValueError:
            return {"raw": r.text}
