"""Resolves (TV, logical key) → driver call. Single entry point for the API."""

from __future__ import annotations

import asyncio

from .codes.library import CodeLibrary
from .drivers.ir_node import IRNode, IRNodeError
from .drivers.roku import RokuClient, RokuError
from .registry import TV, Registry, KeyStep


class DispatchError(RuntimeError):
    pass


class Dispatcher:
    def __init__(self, registry: Registry, codes: CodeLibrary, *, timeout: float = 5.0) -> None:
        self._registry = registry
        self._codes = codes
        self._timeout = timeout

    # ---- Public API ----
    async def power(self, tv_id: str, state: str = "toggle") -> None:
        tv = self._registry.get(tv_id)
        if tv.type == "roku":
            client = RokuClient(tv.url, timeout=self._timeout)
            mapping = {"on": "PowerOn", "off": "PowerOff", "toggle": "Power"}
            try:
                await client.keypress(mapping.get(state, "Power"))
            except RokuError as exc:
                raise DispatchError(str(exc)) from exc
            return
        # IR TVs almost always have a single Power toggle.
        await self._send_logical(tv, "Power")

    async def key(self, tv_id: str, logical: str) -> None:
        tv = self._registry.get(tv_id)
        await self._send_logical(tv, logical)

    async def preset(self, tv_id: str, preset_num: int) -> None:
        tv = self._registry.get(tv_id)
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
        # TV-level alias overrides (e.g. {"Enter": "OK"}).
        button = tv.key_map.get(logical, logical)

        if tv.type == "roku":
            client = RokuClient(tv.url, timeout=self._timeout)
            try:
                await client.send_logical(button)
            except RokuError as exc:
                raise DispatchError(str(exc)) from exc
            return

        if not tv.codes:
            raise DispatchError(f"TV {tv.id} has no codes file configured")
        try:
            command = self._codes.get(tv.codes, button)
        except KeyError as exc:
            raise DispatchError(str(exc)) from exc

        node = IRNode(tv.url, timeout=self._timeout)
        try:
            await node.send(command)
        except IRNodeError as exc:
            raise DispatchError(str(exc)) from exc
