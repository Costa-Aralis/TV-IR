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

    # ---- Public API ----
    async def power(self, tv_id: str, state: str = "toggle") -> None:
        tv = self._registry.get(tv_id)
        if tv.type == "tbd":
            raise DispatchError(f"{tv.id} is TBD")
        if tv.type == "vizio":
            key = {"on": "PowerOn", "off": "PowerOff", "toggle": "Power"}.get(state, "Power")
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
                # webOS drops WiFi in standby — magic packet is the only way in.
                if tv.mac:
                    try:
                        wol.send(tv.mac)
                    except wol.WolError as exc:
                        raise DispatchError(f"wol: {exc}") from exc
                else:
                    raise DispatchError(
                        f"{tv.id}: 'on' requires `mac:` in tvs.yaml for WoL"
                    )
                return
            # toggle: sending POWER on the WS only works while TV is on.
            await self._send_logical(tv, "Power")
            return
        if tv.type == "androidtv" or tv.type == "firetv":
            key = {"on": "PowerOn", "off": "PowerOff", "toggle": "Power"}.get(state, "Power")
            await self._send_logical(tv, key)
            return
        if tv.type == "roku":
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

        # Roku TVs need to be on the Live TV input before digit keys mean
        # anything — otherwise the digits get eaten as menu navigation.
        if tv.type == "roku":
            client = RokuClient(tv.url, timeout=self._timeout)
            try:
                await client.keypress("InputTuner")
            except RokuError:
                pass  # if it fails, the digit sequence will surface the issue
            await asyncio.sleep(1.0)

        sequence = self._registry.preset_sequence(tv, preset_num)
        gap = self._registry.gap_ms(tv) / 1000.0
        for step in sequence:
            if isinstance(step, dict):
                delay = step.get("delay_ms")
                if delay is not None:
                    await asyncio.sleep(delay / 1000.0)
                continue
            await self._send_logical(tv, step)
            await asyncio.sleep(gap)

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
            raise DispatchError(f"unknown tv.type: {tv.type!r}")
        except (VizioError, LgError, AdbError, RokuError, IRNodeError, KeyError) as exc:
            raise DispatchError(str(exc)) from exc

    def _lg(self, tv: TV) -> LgClient:
        host = tv.url.replace("ws://", "").replace("wss://", "").rstrip("/")
        client_key = self._pairings.get(tv.id).get("client_key")
        return LgClient(host, client_key=client_key, timeout=self._timeout)

    def _adb(self, tv: TV) -> AdbClient:
        return AdbClient(tv.url, self._adb_key_path, timeout=self._timeout)
