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


# CODESET / CODE pairs for the keys we need. Reference: pyvizio.const.
#   CODESET 11 = numeric / power.
#     CODE 0..2  = power off / on / toggle
#     CODE 4..13 = number pad 0..9
#     CODE 14    = DASH (subchannel separator)
#   CODESET  5 = volume / mute.
#   CODESET  8 = channel up / down / previous.
#   CODESET  3 = D-pad (incl. OK on CODE 2 — NOT codeset 4).
#   CODESET  4 = BACK / HOME / MENU / INFO.
#   CODESET  7 = input cycling.
_KEYS: dict[str, tuple[int, int]] = {
    # logical key:  (codeset, code)
    "0":            (11, 4),
    "1":            (11, 5),
    "2":            (11, 6),
    "3":            (11, 7),
    "4":            (11, 8),
    "5":            (11, 9),
    "6":            (11, 10),
    "7":            (11, 11),
    "8":            (11, 12),
    "9":            (11, 13),
    "Dot":          (11, 14),   # DASH — subchannel separator
    "Dash":         (11, 14),
    "Enter":        (3,  2),    # DPAD_OK (NOT codeset 4 — that's INFO/BACK/HOME)
    "Ok":           (3,  2),
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

    async def get_current_channel(self) -> str | None:
        """The TV's current channel as it reports it, e.g. '35-2'.

        Read-only — exposed under /menu_native/dynamic/tv_settings/channels
        (CNAME=current_channel). V-series firmware uses '-' for the
        subchannel separator, not '.'.
        """
        data = await self._get("/menu_native/dynamic/tv_settings/channels")
        for item in data.get("ITEMS") or []:
            if item.get("CNAME") == "current_channel":
                v = item.get("VALUE")
                return str(v) if v is not None else None
        return None

    async def get_channel_list(self) -> list[str]:
        """Ordered list of channels in the TV's scanned-channel database.

        Pulled from the Skip Channel submenu, which has one entry per
        scanned channel. Each entry's NAME looks like '30-2 VIDEO'; we
        keep just the channel token.
        """
        data = await self._get("/menu_native/dynamic/tv_settings/channels/skip_channel")
        result: list[str] = []
        for item in data.get("ITEMS") or []:
            name = item.get("NAME") or ""
            token = name.split(" ", 1)[0] if name else ""
            if token:
                result.append(token)
        return result

    async def tune_to(self, target: str, *, step_pause: float = 0.5) -> bool:
        """Reach `target` channel deterministically via the right number of
        CHANNEL_UP presses.

        V-series SmartCast firmware doesn't expose digit keys and
        current_channel API updates lag behind the actual tuner. Polling
        is unreliable — but the scan database (Skip Channel menu) tells us
        the exact ordered cycle, so we compute the delta and fire that
        many keypresses, no polling needed.

        target accepts '30.2' or '30-2'.
        """
        import asyncio
        target_h = target.replace(".", "-")

        try:
            channels = await self.get_channel_list()
        except VizioError:
            return False
        if not channels:
            return False

        current = await self.get_current_channel()
        try:
            cur_idx = channels.index(current) if current else 0
        except ValueError:
            cur_idx = 0  # current isn't in the list — start from the top
        try:
            tgt_idx = channels.index(target_h)
        except ValueError:
            return False  # target isn't in the scanned list

        n = len(channels)
        steps = (tgt_idx - cur_idx) % n
        if steps == 0:
            return True

        for _ in range(steps):
            await self.keypress(8, 1)  # CHANNEL_UP
            await asyncio.sleep(step_pause)
        return True

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

    # ---- Settings ----
    async def get_power_mode(self) -> str | None:
        """Return the TV's current power mode (e.g. 'Quick Start' or 'Eco Mode')."""
        data = await self._get("/menu_native/dynamic/tv_settings/system/power_mode")
        items = data.get("ITEMS") or []
        if not items:
            return None
        return items[0].get("VALUE")

    async def set_quick_start(self) -> bool:
        """Set Power Mode → Quick Start so the TV's WiFi stays awake in
        standby (required for WoL to actually wake the set).

        Returns True if changed, False if already Quick Start. Raises
        VizioError on auth or protocol failure.
        """
        data = await self._get("/menu_native/dynamic/tv_settings/system/power_mode")
        items = data.get("ITEMS") or []
        if not items:
            raise VizioError("power_mode menu item not found on this TV")
        item = items[0]
        if (item.get("VALUE") or "").lower() in ("quick start", "quickstart"):
            return False
        body = {
            "REQUEST": "MODIFY",
            "VALUE": "Quick Start",
            "HASHVAL": item.get("HASHVAL"),
        }
        result = await self._put(
            "/menu_native/dynamic/tv_settings/system/power_mode", body
        )
        status = (result.get("STATUS") or {}).get("RESULT")
        if status != "SUCCESS":
            raise VizioError(f"set_quick_start: {result}")
        return True

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
