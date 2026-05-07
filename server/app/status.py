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

    async def _sweep(self) -> None:
        results = await asyncio.gather(
            *(self._probe(tv) for tv in self._registry.tvs),
            return_exceptions=True,
        )
        now = time.time()
        for tv, res in zip(self._registry.tvs, results):
            if isinstance(res, Exception):
                self._state[tv.id] = TvStatus(False, now, str(res))
            else:
                ok, err = res
                self._state[tv.id] = TvStatus(ok, now, err)

    async def _probe(self, tv: TV) -> tuple[bool, str | None]:
        if tv.type == "tbd":
            return False, "tbd"
        try:
            if tv.type == "roku":
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    r = await c.get(tv.url + "/")
                return r.status_code == 200, None
            if tv.type == "vizio":
                async with httpx.AsyncClient(timeout=self._timeout, verify=False) as c:
                    r = await c.get(f"{tv.url.rstrip('/')}/state/device/power_mode/")
                # 401 (no auth) still proves reachability; just not authed
                return r.status_code in (200, 401), None
            if tv.type in ("lg", "androidtv", "firetv", "ir"):
                host, _, port_s = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/").partition(":")
                port = int(port_s) if port_s else _default_port(tv.type)
                return await _tcp_probe(host, port, self._timeout), None
            return False, f"unknown type {tv.type!r}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)


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
