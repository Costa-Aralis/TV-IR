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
    def __init__(self, registry: Registry, *, interval_s: float = 8.0, timeout_s: float = 3.0) -> None:
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
        import logging
        log = logging.getLogger("tvir.status")
        while not self._stop.is_set():
            try:
                # Hard cap on sweep duration so a single misbehaving probe
                # (LG WS hanging mid-handshake, Vizio mid-tune-cycle) can't
                # block the next tick. Generous so the slowest probe
                # (Vizio's /channels at 2-6 sec) comfortably fits.
                await asyncio.wait_for(self._sweep(), timeout=max(self._interval * 1.5, 12.0))
            except asyncio.TimeoutError:
                log.warning("status sweep exceeded %.1fs; continuing", self._interval)
            except Exception:  # noqa: BLE001
                log.exception("status sweep crashed; continuing")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    def set_pairings(self, pairings) -> None:
        """Wire in the Pairings store so we can read auth-gated channel info."""
        self._pairings = pairings

    def set_channel(self, tv_id: str, channel: str | None) -> None:
        """Update the cached channel for a TV without waiting for a sweep.

        The dispatcher calls this right after a successful tune so the UI's
        "now playing" reflects reality on the next 5-sec poll instead of
        waiting up to 8 sec for the next server sweep (and only then if
        that sweep's channel fetch succeeded).
        """
        import time as _t
        prev = self._state.get(tv_id)
        if prev is None:
            return
        channel_rf = channel.replace("-", ".") if channel else None
        self._state[tv_id] = TvStatus(
            reachable=True,
            last_check_ts=_t.time(),
            last_error=None,
            channel=channel,
            channel_rf=channel_rf,
        )

    async def _sweep(self) -> None:
        tvs = list(self._registry.tvs)  # snapshot once so the zip below aligns
        results = await asyncio.gather(
            *(self._probe(tv) for tv in tvs),
            return_exceptions=True,
        )
        now = time.time()
        for tv, res in zip(tvs, results):
            if isinstance(res, Exception):
                ok, err, channel = False, str(res), None
            else:
                ok, err, channel = res

            prev = self._state.get(tv.id)

            # Debounce: a TV that was reachable in the previous sweep gets
            # one free pass on a transient failure. Vizios in particular go
            # briefly unresponsive while they're tuning, and we don't want
            # the dot to flash red for one cycle every time.
            if not ok and prev is not None and prev.reachable \
                    and now - prev.last_check_ts < self._interval * 2.5:
                ok = True
                err = None  # we're papering over this one

            # Preserve last-known channel if this sweep didn't get a fresh
            # read. Keep it indefinitely until a newer value arrives or the
            # TV goes truly unreachable — channels endpoint can flake for
            # minutes at a time without the TV actually changing state.
            if channel is None and prev is not None and prev.channel:
                channel = prev.channel

            channel_rf = channel.replace("-", ".") if channel else None
            self._state[tv.id] = TvStatus(ok, now, err, channel, channel_rf)

    async def _probe(self, tv: TV) -> tuple[bool, str | None, str | None]:
        if tv.type == "tbd":
            return False, "tbd", None
        if tv.type == "defective":
            return False, "defective", None
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
                # Vizio's HTTPS API is reliably slow (~1-2 sec) and goes
                # briefly unresponsive while tuning. Give it more slack
                # than the other probes.
                vizio_timeout = max(self._timeout * 2, 6.0)
                # Send AUTH if we have it — some newer SmartCast firmware
                # 403s unauthenticated GETs even to read-only state endpoints.
                headers = {}
                pairings = getattr(self, "_pairings", None)
                token = pairings.get(tv.id).get("auth_token") if pairings else None
                if token:
                    headers["AUTH"] = token
                async with httpx.AsyncClient(timeout=vizio_timeout, verify=False) as c:
                    r = await c.get(
                        f"{tv.url.rstrip('/')}/state/device/power_mode/",
                        headers=headers,
                    )
                # Any HTTP response (including 401/403/404) means the TV is
                # alive — only timeouts / connection errors are "unreachable".
                # Channel fetch needs a 200 though.
                ch = await self._vizio_channel(tv) if r.status_code == 200 else None
                return True, None, ch
            if tv.type == "lg":
                host, _, port_s = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/").partition(":")
                port = int(port_s) if port_s else _default_port(tv.type)
                ok = await _tcp_probe(host, port, self._timeout)
                ch = await self._lg_channel(tv) if ok else None
                return ok, None, ch
            if tv.type in ("androidtv", "firetv", "ir"):
                # Android/Fire TV channel reporting is firmware-fragile (TIF
                # database lives behind a ContentResolver; no clean ADB read).
                # Reachability only for now.
                host, _, port_s = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/").partition(":")
                port = int(port_s) if port_s else _default_port(tv.type)
                return await _tcp_probe(host, port, self._timeout), None, None
            return False, f"unknown type {tv.type!r}", None
        except Exception as exc:  # noqa: BLE001
            return False, str(exc), None

    async def _lg_channel(self, tv: TV) -> str | None:
        """Query LG webOS for the current channel via aiowebostv.

        Wrapped in a hard wait_for so a misbehaving WebSocket can't hold up
        the rest of the sweep. Best-effort: any exception → None.
        """
        try:
            return await asyncio.wait_for(self._lg_channel_inner(tv), timeout=self._timeout)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            return None

    async def _lg_channel_inner(self, tv: TV) -> str | None:
        pairings = getattr(self, "_pairings", None)
        if pairings is None:
            return None
        client_key = pairings.get(tv.id).get("client_key")
        if not client_key:
            return None
        host = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/")
        from aiowebostv import WebOsClient
        client = WebOsClient(host, client_key=client_key)
        try:
            await client.connect()
        except Exception:  # noqa: BLE001
            return None
        try:
            ch = None
            fn = getattr(client, "get_current_channel", None)
            if callable(fn):
                try:
                    info = await fn()
                    if isinstance(info, dict):
                        ch = info.get("channelNumber") or info.get("channelName")
                except Exception:  # noqa: BLE001
                    pass
            if not ch:
                cur = getattr(client, "current_channel", None)
                if isinstance(cur, dict):
                    ch = cur.get("channelNumber")
            return str(ch) if ch else None
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def _vizio_channel(self, tv: TV) -> str | None:
        pairings = getattr(self, "_pairings", None)
        if pairings is None:
            return None
        token = pairings.get(tv.id).get("auth_token") if pairings else None
        if not token:
            return None
        # Vizio's /channels endpoint takes 2-6 sec to respond — the default
        # 3-sec probe timeout was silently swallowing the response, making
        # channel always come back None.
        timeout = max(self._timeout * 2, 6.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as c:
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
