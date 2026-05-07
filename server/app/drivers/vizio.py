"""Vizio SmartCast HTTP driver.

The TV exposes an HTTPS API on port 7345 (or 9000 on older models). Auth is a
token returned from a one-time PIN pairing flow; the token is sent in the
`AUTH` header on every subsequent request.

Reference: https://github.com/exiva/Vizio_SmartCast_API (community-reverse-engineered)
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import httpx


# CODESET / CODE pairs for the keys we need. Most TV models accept these on
# CODESET 11 (for digits), CODESET 4 (Enter / OK), CODESET 8 (channel),
# CODESET 11 CODE 1 / 0 (POWER_ON / POWER_OFF).
_KEYS: dict[str, tuple[int, int]] = {
    # logical key:  (codeset, code)
    "0":            (11, 0),
    "1":            (11, 1),
    "2":            (11, 2),
    "3":            (11, 3),
    "4":            (11, 4),
    "5":            (11, 5),
    "6":            (11, 6),
    "7":            (11, 7),
    "8":            (11, 8),
    "9":            (11, 9),
    "Enter":        (4,  0),
    "Ok":           (4,  0),
    "Dot":          (11, 11),   # Vizio "DASH" / "-" subchannel separator
    "Dash":         (11, 11),
    "Vol_up":       (5,  1),
    "Vol_dn":       (5,  0),
    "Mute":         (5,  3),
    "Ch_next":      (8,  1),
    "Ch_prev":      (8,  0),
    "Power":        (11, 2),    # POWER_TOGGLE
    "PowerOn":      (11, 1),
    "PowerOff":     (11, 0),
    "Up":           (3,  8),
    "Down":         (3,  0),
    "Left":         (3,  1),
    "Right":        (3,  7),
    "Back":         (4,  3),
    "Menu":         (4,  8),
}


class VizioError(RuntimeError):
    pass


def _client(timeout: float) -> httpx.AsyncClient:
    # SmartCast TVs use a self-signed cert. Skipping verify is the standard
    # approach in every community client. Constrained to the LAN scope.
    return httpx.AsyncClient(timeout=timeout, verify=False)


class VizioClient:
    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._token = auth_token
        self._timeout = timeout

    # ---- Public API ----
    async def keypress(self, codeset: int, code: int) -> None:
        body = {
            "KEYLIST": [
                {"CODESET": codeset, "CODE": code, "ACTION": "KEYPRESS"}
            ]
        }
        await self._put("/key_command/", body)

    async def send_logical(self, key: str) -> None:
        pair = _KEYS.get(key)
        if pair is None:
            raise VizioError(f"unsupported key: {key!r}")
        await self.keypress(*pair)

    async def power_state(self) -> bool:
        data = await self._get("/state/device/power_mode/")
        items = data.get("ITEMS") or []
        if not items:
            raise VizioError("power_mode returned no items")
        return bool(items[0].get("VALUE"))

    async def healthy(self) -> bool:
        try:
            await self._get("/state/device/power_mode/")
            return True
        except (VizioError, httpx.HTTPError):
            return False

    # ---- Pairing ----
    async def pair_start(self, device_name: str = "tv-ir") -> int:
        """Trigger the on-screen PIN. Returns the challenge token."""
        body = {
            "DEVICE_NAME": device_name,
            "DEVICE_ID":   _device_id(device_name),
        }
        data = await self._put("/pairing/start", body, auth=False)
        item = (data.get("ITEM") or {})
        challenge = item.get("PAIRING_REQ_TOKEN")
        if challenge is None:
            raise VizioError(f"start: unexpected response {data!r}")
        return int(challenge)

    async def pair_finish(
        self, challenge: int, pin: str, device_name: str = "tv-ir"
    ) -> str:
        """Submit the PIN; returns the persistent auth token."""
        body = {
            "DEVICE_NAME":        device_name,
            "DEVICE_ID":          _device_id(device_name),
            "CHALLENGE_TYPE":     1,
            "RESPONSE_VALUE":     str(pin),
            "PAIRING_REQ_TOKEN":  int(challenge),
        }
        data = await self._put("/pairing/pair", body, auth=False)
        item = (data.get("ITEM") or {})
        token = item.get("AUTH_TOKEN")
        if not token:
            raise VizioError(f"pair: unexpected response {data!r}")
        self._token = token
        return token

    # ---- HTTP helpers ----
    async def _get(self, path: str) -> dict[str, Any]:
        return await self._request("GET", path, None, auth=True)

    async def _put(self, path: str, body: dict[str, Any], *, auth: bool = True) -> dict[str, Any]:
        return await self._request("PUT", path, body, auth=auth)

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        auth: bool,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth:
            if not self._token:
                raise VizioError("no auth token — pair first")
            headers["AUTH"] = self._token
        try:
            async with _client(self._timeout) as client:
                r = await client.request(method, f"{self._base}{path}", headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise VizioError(f"vizio unreachable at {self._base}: {exc}") from exc
        if r.status_code >= 400:
            raise VizioError(f"vizio {r.status_code}: {r.text}")
        try:
            return r.json()
        except ValueError as exc:
            raise VizioError(f"non-json response: {r.text!r}") from exc


def _device_id(name: str) -> str:
    """Stable id for this controller — Vizio echoes it back in pair_finish."""
    host = socket.gethostname() or "tvir"
    return f"{name}@{host}"
