"""Background reachability poller.

Pings each TV every N seconds via its native protocol's lightweight check
(HTTP GET for Roku/Vizio, ECP `/` for Roku, ICMP-equivalent TCP probe for
ADB/LG). Caches the last seen state so the API can answer instantly.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass

import httpx

from .registry import TV, Registry


@dataclass
class TvStatus:
    reachable: bool
    last_check_ts: float
    last_error: str | None = None
    channel: str | None = None     # current channel as the TV reports it
    channel_rf: str | None = None  # normalized "30.2" form, derived from channel


class StatusMonitor:
    def __init__(self, registry: Registry, *, interval_s: float = 15.0, timeout_s: float = 3.0) -> None:
        self._registry = registry
        self._interval = interval_s
        self._timeout = timeout_s
        self._state: dict[str, TvStatus] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def get(self, tv_id: str) -> TvStatus | None:
        return self._state.get(tv_id)

    def all(self) -> dict[str, TvStatus]:
        return dict(self._state)

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="status-monitor")

    async def stop(self) -> None:
        if self._task is not None:
            self._stop.set()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self._sweep()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def set_pairings(self, pairings) -> None:
        """Wire in the Pairings store so we can read auth-gated channel info."""
        self._pairings = pairings

    async def _sweep(self) -> None:
        tvs = list(self._registry.tvs)  # snapshot once so the zip below aligns
        results = await asyncio.gather(
            *(self._probe(tv) for tv in tvs),
            return_exceptions=True,
        )
        now = time.time()
        for tv, res in zip(tvs, results):
            if isinstance(res, Exception):
                self._state[tv.id] = TvStatus(False, now, str(res))
                continue
            ok, err, channel = res
            channel_rf = channel.replace("-", ".") if channel else None
            self._state[tv.id] = TvStatus(ok, now, err, channel, channel_rf)

    async def _probe(self, tv: TV) -> tuple[bool, str | None, str | None]:
        if tv.type == "tbd":
            return False, "tbd", None
        try:
            if tv.type == "roku":
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    r = await c.get(tv.url + "/")
                if r.status_code != 200:
                    return False, None, None
                # Roku also reports the currently-tuned channel under /query/tv-active-channel
                ch = await self._roku_channel(tv.url)
                return True, None, ch
            if tv.type == "vizio":
                async with httpx.AsyncClient(timeout=self._timeout, verify=False) as c:
                    r = await c.get(f"{tv.url.rstrip('/')}/state/device/power_mode/")
                # 401 (no auth) still proves reachability; just not authed
                if r.status_code not in (200, 401):
                    return False, None, None
                # If we have an auth token, fetch the current channel too.
                ch = await self._vizio_channel(tv) if r.status_code == 200 else None
                return True, None, ch
            if tv.type in ("lg", "androidtv", "firetv", "ir"):
                host, _, port_s = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/").partition(":")
                port = int(port_s) if port_s else _default_port(tv.type)
                return await _tcp_probe(host, port, self._timeout), None, None
            return False, f"unknown type {tv.type!r}", None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), None

    async def _vizio_channel(self, tv: TV) -> str | None:
        pairings = getattr(self, "_pairings", None)
        if pairings is None:
            return None
        token = pairings.get(tv.id).get("auth_token") if pairings else None
        if not token:
            return None
        try:
            async with httpx.AsyncClient(timeout=self._timeout, verify=False) as c:
                r = await c.get(
                    f"{tv.url.rstrip('/')}/menu_native/dynamic/tv_settings/channels",
                    headers={"AUTH": token},
                )
            if r.status_code != 200:
                return None
            data = r.json()
            for item in data.get("ITEMS") or []:
                if item.get("CNAME") == "current_channel":
                    v = item.get("VALUE")
                    return str(v) if v else None
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _roku_channel(self, base_url: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.get(f"{base_url.rstrip('/')}/query/tv-active-channel")
            if r.status_code != 200 or "<no-channel/>" in r.text:
                return None
            # parse <channel><number>30.2</number>...
            import re
            m = re.search(r"<number>([^<]+)</number>", r.text)
            return m.group(1) if m else None
        except Exception:  # noqa: BLE001
            return None


def _default_port(t: str) -> int:
    return {"lg": 3000, "androidtv": 5555, "firetv": 5555, "ir": 80}.get(t, 80)


async def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(
            loop.run_in_executor(None, _sync_connect, host, port, timeout),
            timeout=timeout + 1.0,
        )
        return True
    except (asyncio.TimeoutError, OSError):
        return False


def _sync_connect(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass
