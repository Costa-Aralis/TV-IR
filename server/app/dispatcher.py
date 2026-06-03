"""Resolves (TV, logical key) → driver call. Single entry point for the API."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .codes.library import CodeLibrary
from .drivers.android_tv import AdbClient, AdbError
from .drivers.ir_node import IRNode, IRNodeError
from .drivers.lg_webos import LgClient, LgError
from .drivers.roku import RokuClient, RokuError
from .drivers.vizio import VizioClient, VizioError
from .drivers import wol
from .registry import TV, KeyStep, Pairings, Registry


class DispatchError(RuntimeError):
    pass


class Dispatcher:
    def __init__(
        self,
        registry: Registry,
        codes: CodeLibrary,
        pairings: Pairings,
        *,
        adb_key_path: Path,
        timeout: float = 5.0,
    ) -> None:
        self._registry = registry
        self._codes = codes
        self._pairings = pairings
        self._adb_key_path = adb_key_path
        self._timeout = timeout
        self._monitor = None  # wired in by main lifespan; see set_monitor

    def set_monitor(self, monitor) -> None:
        """Attach the StatusMonitor so we can push channel updates the moment
        a tune lands, instead of waiting for the next 8-sec sweep."""
        self._monitor = monitor

    # ---- Public API ----
    async def power(self, tv_id: str, state: str = "toggle") -> None:
        tv = self._registry.get(tv_id)
        if tv.type == "tbd":
            raise DispatchError(f"{tv.id} is TBD")
        if tv.type == "defective":
            raise DispatchError(f"{tv.id} is marked defective — replace the TV")

        # Universal: WoL fires first whenever we're waking a TV that has a
        # `mac:` configured. Most modern smart TVs drop their WiFi in deep
        # standby (Vizio SmartCast, LG webOS, many Samsungs) so a plain API
        # "PowerOn" call would never reach them. The magic packet is harmless
        # if the TV is already awake.
        #
        # Aim it at the TV's subnet-directed broadcast (e.g. 172.16.20.255)
        # so on a multi-NIC LXC the packet goes out the right interface.
        if state == "on" and tv.mac:
            host_ip = _host_from_url(tv.url)
            try:
                if host_ip:
                    wol.send_to_host(tv.mac, host_ip)
                else:
                    wol.send(tv.mac)
            except wol.WolError as exc:
                raise DispatchError(f"wol: {exc}") from exc

        if tv.type == "vizio":
            if state == "on":
                # WoL above wakes it; try the SmartCast PowerOn too in case
                # the TV's already up — best-effort, ignore failure since
                # WoL alone is usually enough.
                try:
                    await self._send_logical(tv, "PowerOn")
                except DispatchError:
                    pass
                return
            key = {"off": "PowerOff", "toggle": "Power"}.get(state, "Power")
            await self._send_logical(tv, key)
            return

        if tv.type == "lg":
            if state == "off":
                lg = self._lg(tv)
                try:
                    await lg.power_off()
                finally:
                    await lg.close()
                return
            if state == "on":
                if not tv.mac:
                    raise DispatchError(
                        f"{tv.id}: 'on' requires `mac:` in tvs.yaml for WoL"
                    )
                return  # WoL above handles it
            # toggle: sending POWER on the WS only works while TV is on.
            await self._send_logical(tv, "Power")
            return

        if tv.type in ("androidtv", "firetv"):
            if state == "on":
                # WoL above; KEYCODE_WAKEUP brings it the rest of the way if
                # the box was awake-on-network in light standby.
                try:
                    await self._send_logical(tv, "PowerOn")
                except DispatchError:
                    pass
                return
            key = {"off": "PowerOff", "toggle": "Power"}.get(state, "Power")
            try:
                await self._send_logical(tv, key)
            except DispatchError:
                # ADB unreachable. For toggle, that almost certainly means the
                # TV is already off — fall back to WoL to wake it. For off,
                # swallow the error; it's already off.
                if state == "toggle" and tv.mac:
                    host_ip = _host_from_url(tv.url)
                    try:
                        if host_ip:
                            wol.send_to_host(tv.mac, host_ip)
                        else:
                            wol.send(tv.mac)
                    except wol.WolError:
                        pass
                elif state != "off":
                    raise
            return

        if tv.type == "roku":
            # Roku ECP works in "fast start" standby; WoL above is insurance.
            key = {"on": "PowerOn", "off": "PowerOff", "toggle": "Power"}.get(state, "Power")
            await self._send_logical(tv, key)
            return

        # IR
        await self._send_logical(tv, "Power")

    async def key(self, tv_id: str, logical: str) -> None:
        tv = self._registry.get(tv_id)
        await self._send_logical(tv, logical)

    async def preset(self, tv_id: str, preset_num: int) -> None:
        tv = self._registry.get(tv_id)

        # Vizio V-series firmware doesn't expose number keys via SmartCast.
        # Walk CHANNEL_UP based on the index delta in the scan list — quick
        # and deterministic with only 8 scanned channels.
        if tv.type == "vizio":
            rf = self._registry.preset_rf_channel(preset_num)
            if not rf:
                raise DispatchError(f"preset {preset_num} has no RF target")
            token = self._pairings.get(tv.id).get("auth_token")
            client = VizioClient(tv.url, auth_token=token, timeout=self._timeout)
            try:
                reached = await client.tune_to(rf)
            except VizioError as exc:
                raise DispatchError(str(exc)) from exc
            if not reached:
                raise DispatchError(f"tune to {rf} didn't land (still wrong channel)")
            # Push the new channel into the status cache so the UI updates
            # on the next poll without waiting for the slow server sweep.
            if self._monitor is not None:
                self._monitor.set_channel(tv.id, rf.replace(".", "-"))
            return

        # Roku TVs need to be on the Live TV input before digit keys mean
        # anything — otherwise the digits get eaten as menu navigation. Probe
        # with the input switch first; if it fails the TV is unreachable, so
        # bail with one clear error instead of firing (and failing) 5 digits.
        if tv.type == "roku":
            client = RokuClient(tv.url, timeout=self._timeout)
            try:
                await client.keypress("InputTuner")
            except RokuError as exc:
                raise DispatchError(str(exc)) from exc
            await asyncio.sleep(1.0)

        # Android TV / Fire TV: launch the Live Channels activity by name
        # before sending digits. KEYCODE_TV (170) is unreliable — on Hisense
        # firmware it's commonly remapped to Netflix. Activity name is per-TV
        # configurable (tv.live_tv_activity); default targets the MediaTek
        # tvcenter app that ships on Hisense 70H6570G.
        if tv.type in ("androidtv", "firetv"):
            activity = tv.live_tv_activity or "com.mediatek.wwtv.tvcenter/.nav.TurnkeyUiMainActivity"
            adb = self._adb(tv)
            try:
                await adb.launch(activity)
            except AdbError:
                pass  # best-effort; fall through to digit entry
            await asyncio.sleep(2.0)

        sequence = self._registry.preset_sequence(tv, preset_num)
        gap = self._registry.gap_ms(tv) / 1000.0

        # LG webOS: one persistent WebSocket for the whole sequence. Reconnect
        # per key was costing ~500 ms each AND racing keys out of order.
        if tv.type == "lg":
            lg = self._lg(tv)
            try:
                async with lg:
                    await lg.send_sequence(sequence, gap, alias_map=tv.key_map)
            except LgError as exc:
                raise DispatchError(str(exc)) from exc
            return

        for step in sequence:
            if isinstance(step, dict):
                delay = step.get("delay_ms")
                if delay is not None:
                    await asyncio.sleep(delay / 1000.0)
                continue
            await self._send_logical(tv, step)
            await asyncio.sleep(gap)

        # Push the channel into the status cache so the tile updates without
        # waiting for a sweep (and without us needing to query the TV — which
        # for Android/Fire TV would require parsing dumpsys output).
        if self._monitor is not None:
            rf = self._registry.preset_rf_channel(preset_num)
            if rf:
                # Hisense / Vizio use '-' separator; the monitor normalizes.
                self._monitor.set_channel(tv.id, rf.replace(".", "-"))

    # ---- Internals ----
    async def _send_logical(self, tv: TV, logical: str) -> None:
        button = tv.key_map.get(logical, logical)
        try:
            if tv.type == "vizio":
                client = VizioClient(
                    tv.url,
                    auth_token=self._pairings.get(tv.id).get("auth_token"),
                    timeout=self._timeout,
                )
                await client.send_logical(button)
                return
            if tv.type == "lg":
                lg = self._lg(tv)
                try:
                    await lg.send_logical(button)
                finally:
                    await lg.close()
                return
            if tv.type in ("androidtv", "firetv"):
                adb = self._adb(tv)
                await adb.send_logical(button)
                return
            if tv.type == "roku":
                roku = RokuClient(tv.url, timeout=self._timeout)
                await roku.send_logical(button)
                return
            if tv.type == "ir":
                if not tv.codes:
                    raise DispatchError(f"{tv.id} has no codes file configured")
                command = self._codes.get(tv.codes, button)
                node = IRNode(tv.url, timeout=self._timeout)
                await node.send(command)
                return
            if tv.type == "tbd":
                raise DispatchError(f"{tv.id} is TBD")
            if tv.type == "defective":
                raise DispatchError(f"{tv.id} is marked defective — replace the TV")
            raise DispatchError(f"unknown tv.type: {tv.type!r}")
        except (VizioError, LgError, AdbError, RokuError, IRNodeError, KeyError) as exc:
            raise DispatchError(str(exc)) from exc

    def _lg(self, tv: TV) -> LgClient:
        host = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/")
        client_key = self._pairings.get(tv.id).get("client_key")
        return LgClient(host, client_key=client_key, timeout=self._timeout)

    def _adb(self, tv: TV) -> AdbClient:
        return AdbClient(tv.url, self._adb_key_path, timeout=self._timeout)


def _host_from_url(url: str) -> str | None:
    """Extract the host IP from a tv.url like 'https://172.16.20.40:7345' or
    'http://1.2.3.4:8060' or '172.16.20.49' or '172.16.20.42:5555'."""
    s = url
    for prefix in ("https://", "http://", "ws://", "wss://"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.split("/", 1)[0]
    host, _, _port = s.partition(":")
    host = host.strip()
    return host or None
