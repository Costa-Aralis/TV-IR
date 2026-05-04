"""Roku External Control Protocol client.

Reference: https://developer.roku.com/docs/developer-program/dev-tools/external-control-api.md
"""

from __future__ import annotations

from typing import Any

import httpx


# Mapping from generic / Flipper-style button names to Roku ECP key names.
# Used so the dispatcher can issue the same logical key to either driver.
ROKU_KEY_MAP: dict[str, str] = {
    "Power":      "Power",
    "PowerOn":    "PowerOn",
    "PowerOff":   "PowerOff",
    "Vol_up":     "VolumeUp",
    "Vol_dn":     "VolumeDown",
    "Mute":       "VolumeMute",
    "Ch_next":    "ChannelUp",
    "Ch_prev":    "ChannelDown",
    "Up":         "Up",
    "Down":       "Down",
    "Left":       "Left",
    "Right":      "Right",
    "Ok":         "Select",
    "Enter":      "Select",
    "Back":       "Back",
    "Home":       "Home",
    "Tv":         "InputTuner",
    "Hdmi1":      "InputHDMI1",
    "Hdmi2":      "InputHDMI2",
    "Hdmi3":      "InputHDMI3",
    "Hdmi4":      "InputHDMI4",
    "0": "Lit_0", "1": "Lit_1", "2": "Lit_2", "3": "Lit_3", "4": "Lit_4",
    "5": "Lit_5", "6": "Lit_6", "7": "Lit_7", "8": "Lit_8", "9": "Lit_9",
    "Dot": "Lit_.",
}


class RokuError(RuntimeError):
    pass


class RokuClient:
    def __init__(self, base_url: str, *, timeout: float = 5.0) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def keypress(self, key: str) -> None:
        """Send a single ECP keypress. `key` should already be a Roku key name."""
        await self._post(f"/keypress/{key}")

    async def send_logical(self, logical: str) -> None:
        """Translate a logical key name into Roku and send."""
        roku_key = ROKU_KEY_MAP.get(logical, logical)
        await self.keypress(roku_key)

    async def info(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(f"{self._base}/query/device-info")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise RokuError(f"roku unreachable at {self._base}: {exc}") from exc
        return {"raw_xml": r.text}

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(f"{self._base}/")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def _post(self, path: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(f"{self._base}{path}")
        except httpx.HTTPError as exc:
            raise RokuError(f"roku unreachable at {self._base}: {exc}") from exc
        if r.status_code >= 400:
            raise RokuError(f"roku returned {r.status_code}: {r.text}")
