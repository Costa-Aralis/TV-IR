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

    async def tune_to(self, target: str, *, step_pause: float = 0.4,
                      verify_pause: float = 1.2) -> bool:
        """Reach `target` antenna channel via D-pad UP/DOWN.

        CHANNEL_UP/DOWN on this firmware cycles through WatchFree+ streaming
        channels in addition to antenna channels. D-pad UP/DOWN walks ONLY
        the antenna list (30-2 .. 37-2) — for the first 7 steps in each
        direction. Press it MORE than that and it eventually spills past
        37-2 into WatchFree+ too (the "cap" looked solid in testing but
        was actually API read lag).

        So the safe algorithm is "send exactly delta presses, no more":
          - Read current and target index.
          - Pick direction (UP if target > current, else DOWN — never wrap).
          - Fire exactly `delta` D-pad presses with a short gap.
          - Settle, then verify. If we landed 1 short (banner-open ate the
            first press), send one corrective press in the same direction.

        `target` accepts '30.2' or '30-2'.
        """
        import asyncio
        target_h = target.replace(".", "-")

        try:
            antenna = await self.get_channel_list()
        except VizioError:
            antenna = []
        if not antenna:
            return False

        current = await self.get_current_channel()
        if current == target_h:
            return True
        if current not in antenna:
            # We're somewhere outside the antenna list (WatchFree+, HDMI,
            # SmartCast home) — no safe path back from here without risking
            # a stray WatchFree+ press.
            return False

        cur_idx = antenna.index(current)
        tgt_idx = antenna.index(target_h)

        if tgt_idx > cur_idx:
            key_code = 8   # D-pad UP
            delta = tgt_idx - cur_idx
        else:
            key_code = 0   # D-pad DOWN
            delta = cur_idx - tgt_idx

        # Send exactly `delta` presses — no polling between, no risk of
        # one extra press spilling into WatchFree+ at the edge.
        for _ in range(delta):
            await self.keypress(3, key_code)
            await asyncio.sleep(step_pause)

        # Let the API catch up (read lag ~1 step), then verify.
        await asyncio.sleep(verify_pause)
        final = await self.get_current_channel()
        if final == target_h:
            return True

        # Off by 1 in either direction (often the channel banner ate the
        # first press, or the TV was being slow). Send one corrective hop.
        if final in antenna:
            final_idx = antenna.index(final)
            if abs(final_idx - tgt_idx) == 1:
                code = 8 if tgt_idx > final_idx else 0
                await self.keypress(3, code)
                await asyncio.sleep(verify_pause)
                final = await self.get_current_channel()
                return final == target_h
        return False

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

    # ---- Input selection ----
    async def get_current_input(self) -> str | None:
        data = await self._get("/menu_native/dynamic/tv_settings/devices/current_input")
        items = data.get("ITEMS") or []
        if not items:
            return None
        raw = items[0].get("VALUE")
        if isinstance(raw, dict):
            return raw.get("NAME")
        return raw

    async def _find_tuner_input_value(self) -> str | None:
        """Walk the inputs list and return the display name of the antenna
        tuner. CNAME for the tuner is normally 'tuner' (sometimes 'tv'); the
        VALUE is the user-visible name like 'TV' that we have to send back.

        VALUE shape varies by firmware: some TVs return a plain string, others
        return a dict like {'NAME':'TV','METADATA':...}."""
        data = await self._get("/menu_native/dynamic/tv_settings/devices/name_input")
        for item in data.get("ITEMS") or []:
            cname = (item.get("CNAME") or "").lower()
            raw = item.get("VALUE")
            if isinstance(raw, dict):
                value = raw.get("NAME") or ""
            else:
                value = raw or ""
            if cname in ("tuner", "tv", "antenna") or value.upper() == "TV":
                return value
        return None

    async def select_tuner_input(self, *, max_cycles: int = 8,
                                  step_pause: float = 1.4) -> bool:
        """Switch to the antenna tuner input. Returns True if a switch was
        actually made; False if already on the tuner.

        After a cold power-on the Vizio lands on SmartCast Home, where
        tune_to() can't navigate the antenna channel list with the D-pad —
        the D-pad walks home-screen tiles instead. Switching to the tuner
        input first restores the in-tuner D-pad-walks-channels behavior.

        Implementation: MODIFY current_input is rejected by V-series firmware
        (that endpoint is for renaming, not switching). The reliable path is
        the remote key INPUT_TOGGLE (CODESET 7 CODE 1), which cycles through
        physical inputs and SmartCast Home. We send it once at a time and
        read current_input back; stop the moment we see TV.
        """
        import asyncio
        tuner_value = await self._find_tuner_input_value() or "TV"
        current = await self.get_current_input()
        if current and current.upper() == tuner_value.upper():
            return False
        for _ in range(max_cycles):
            await self.keypress(7, 1)  # INPUT_TOGGLE
            await asyncio.sleep(step_pause)
            current = await self.get_current_input()
            if current and current.upper() == tuner_value.upper():
                return True
        raise VizioError(
            f"could not reach tuner input after {max_cycles} cycles "
            f"(last current={current!r}, looking for {tuner_value!r})"
        )

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
