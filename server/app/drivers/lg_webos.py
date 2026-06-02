"""LG webOS driver (TVs running webOS — UQ75/UP73/etc.).

Speaks the documented LG SSAP protocol over a websocket on :3000 (insecure)
or :3001 (TLS, self-signed). One-time pairing produces a persistent
client_key the TV remembers; subsequent connects pass it back to skip the
on-screen accept prompt.

We use the well-maintained `aiowebostv` library which handles the protocol
and reconnection details.
"""

from __future__ import annotations

from typing import Any

from aiowebostv import WebOsClient, WebOsTvPairError


class LgError(RuntimeError):
    pass


class LgClient:
    """Wraps `aiowebostv.WebOsClient` with the dispatch surface we need."""

    def __init__(
        self,
        host: str,
        client_key: str | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        # WebOsClient constructor signature: (host, client_key=None, ...)
        self._host = host
        self._client_key = client_key
        self._timeout = timeout
        self._client: WebOsClient | None = None

    async def __aenter__(self) -> "LgClient":
        await self._connect()
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self.close()

    async def _connect(self) -> None:
        if self._client is not None:
            return
        client = WebOsClient(self._host, client_key=self._client_key)
        try:
            await client.connect()
        except WebOsTvPairError as exc:
            raise LgError(f"lg pair required: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LgError(f"lg connect failed: {exc}") from exc
        self._client = client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    @property
    def client_key(self) -> str | None:
        if self._client and self._client.client_key:
            return self._client.client_key
        return self._client_key

    # ---- Commands ----
    async def power_off(self) -> None:
        await self._connect()
        try:
            await self._client.power_off()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            raise LgError(f"power_off: {exc}") from exc

    async def send_logical(self, key: str) -> None:
        """Send a remote-button event. Maps logical names to LG button codes."""
        await self._connect()
        button = _BUTTON_MAP.get(key, key)
        try:
            await self._client.button(button)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            raise LgError(f"button {button}: {exc}") from exc

    async def send_sequence(
        self, keys: list, gap_s: float, alias_map: dict[str, str] | None = None
    ) -> None:
        """Send a sequence of logical buttons over a single connection.

        `keys` is the raw preset list: strings are buttons, dicts may carry a
        `delay_ms`. Sending all keys on one WebSocket avoids reconnect overhead
        AND guarantees the TV sees them in order.
        """
        await self._connect()
        alias_map = alias_map or {}
        for step in keys:
            if isinstance(step, dict):
                delay = step.get("delay_ms")
                if delay is not None:
                    import asyncio
                    await asyncio.sleep(delay / 1000.0)
                continue
            logical = alias_map.get(step, step)
            button = _BUTTON_MAP.get(logical, logical)
            try:
                await self._client.button(button)  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                raise LgError(f"button {button}: {exc}") from exc
            if gap_s > 0:
                import asyncio
                await asyncio.sleep(gap_s)

    async def healthy(self) -> bool:
        try:
            await self._connect()
            return True
        except LgError:
            return False


# webOS uses uppercase button codes over SSAP.
_BUTTON_MAP: dict[str, str] = {
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    "Enter":     "ENTER",
    "Ok":        "ENTER",
    "Dot":       "DASH",
    "Dash":      "DASH",
    "Vol_up":    "VOLUMEUP",
    "Vol_dn":    "VOLUMEDOWN",
    "Mute":      "MUTE",
    "Ch_next":   "CHANNELUP",
    "Ch_prev":   "CHANNELDOWN",
    "Up":        "UP",
    "Down":      "DOWN",
    "Left":      "LEFT",
    "Right":     "RIGHT",
    "Back":      "BACK",
    "Home":      "HOME",
    "Menu":      "MENU",
    "Power":     "POWER",
}
