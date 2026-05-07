"""Cron-style scheduler for shift automation.

Reads a `schedule:` block from tvs.yaml — a list of entries like:

    schedule:
      - { when: "0 11 * * *",  action: open }
      - { when: "0 2  * * *",  action: close }
      - { when: "0 12 * * 0",  action: all_to_preset, preset: 1 }   # Sun ESPN
      - { when: "30 18 * * 4", action: event, event_id: "thursday_night" }

Field semantics: standard 5-field cron (`minute hour dom month dow`), with
`*`, ranges, lists, and `*/N` step. Timezone defaults to the container's
`TZ` env var (set to America/Chicago for Rocky's).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import os


log = logging.getLogger("tvir.scheduler")


@dataclass
class ScheduledJob:
    when: str
    action: str
    params: dict[str, Any]


class CronExpr:
    """Minimal cron parser/matcher — minute, hour, dom, month, dow."""

    def __init__(self, expr: str) -> None:
        parts = expr.split()
        if len(parts) != 5:
            raise ValueError(f"cron must have 5 fields, got {expr!r}")
        self.minute  = self._parse(parts[0], 0, 59)
        self.hour    = self._parse(parts[1], 0, 23)
        self.dom     = self._parse(parts[2], 1, 31)
        self.month   = self._parse(parts[3], 1, 12)
        self.dow     = self._parse(parts[4], 0, 6)  # 0 = Mon, 6 = Sun (Python convention)

    def matches(self, dt: datetime) -> bool:
        # Python: Monday=0..Sunday=6. Cron: Sunday=0..Saturday=6.
        # Accept both: convert dt.weekday() (Mon=0) AND (dt.weekday()+1)%7 (Sun=0).
        py_dow = dt.weekday()
        cron_dow = (py_dow + 1) % 7
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.dom
            and dt.month in self.month
            and (py_dow in self.dow or cron_dow in self.dow)
        )

    @staticmethod
    def _parse(field: str, lo: int, hi: int) -> set[int]:
        out: set[int] = set()
        for piece in field.split(","):
            step = 1
            if "/" in piece:
                piece, step_s = piece.split("/", 1)
                step = int(step_s)
            if piece in ("*", ""):
                start, end = lo, hi
            elif "-" in piece:
                a, b = piece.split("-", 1)
                start, end = int(a), int(b)
            else:
                start = end = int(piece)
            out.update(range(start, end + 1, step))
        return {v for v in out if lo <= v <= hi}


class Scheduler:
    """Runs the schedule block at minute granularity in a background task."""

    def __init__(self, jobs: list[ScheduledJob], dispatcher, registry) -> None:
        self._jobs = jobs
        self._dispatcher = dispatcher
        self._registry = registry
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        tz = os.environ.get("TZ", "America/Chicago")
        try:
            self._tz = ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            self._tz = ZoneInfo("UTC")
        self._exprs = [(CronExpr(j.when), j) for j in jobs]

    async def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._stop.set()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        # Sleep until the next minute boundary, then tick once per minute.
        while not self._stop.is_set():
            now = datetime.now(self._tz)
            for cron, job in self._exprs:
                if cron.matches(now):
                    log.info("[scheduler] firing %s (%s)", job.action, job.when)
                    asyncio.create_task(self._fire(job))
            # sleep until top of next minute
            sleep_s = 60 - now.second
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
            except asyncio.TimeoutError:
                pass

    async def _fire(self, job: ScheduledJob) -> None:
        try:
            if job.action == "open":
                await self._open()
            elif job.action == "close":
                await self._close()
            elif job.action == "all_to_preset":
                preset = int(job.params.get("preset", 1))
                await self._all_preset(preset)
            elif job.action == "event":
                event_id = job.params.get("event_id")
                await self._fire_event(event_id)
            else:
                log.warning("unknown action: %r", job.action)
        except Exception:
            log.exception("scheduler job failed: %r", job)

    async def _open(self) -> None:
        for tv in self._registry.tvs:
            if tv.type == "tbd":
                continue
            try:
                await self._dispatcher.power(tv.id, "on")
            except Exception:
                log.exception("open: %s", tv.id)

    async def _close(self) -> None:
        for tv in self._registry.tvs:
            if tv.type == "tbd":
                continue
            try:
                await self._dispatcher.power(tv.id, "off")
            except Exception:
                log.exception("close: %s", tv.id)

    async def _all_preset(self, preset: int) -> None:
        for tv in self._registry.tvs:
            if tv.type == "tbd":
                continue
            try:
                await self._dispatcher.preset(tv.id, preset)
            except Exception:
                log.exception("preset: %s", tv.id)

    async def _fire_event(self, event_id: str | None) -> None:
        if event_id is None:
            return
        # Re-use the event-application code path.
        from .api.scenes import _resolve_targets, _safe
        event = next((e for e in self._registry.events if e.id == event_id), None)
        if event is None:
            log.warning("scheduled event not found: %r", event_id)
            return
        for action in event.actions:
            targets = _resolve_targets(self._registry, action.target)
            coros = []
            for tv in targets:
                if action.power == "on":
                    coros.append(_safe(self._dispatcher.power(tv.id, "on"), tv.id))
                elif action.power == "off":
                    coros.append(_safe(self._dispatcher.power(tv.id, "off"), tv.id))
                if action.preset:
                    coros.append(_safe(self._dispatcher.preset(tv.id, action.preset), tv.id))
            await asyncio.gather(*coros)


def load_jobs(raw: list[dict]) -> list[ScheduledJob]:
    jobs: list[ScheduledJob] = []
    for entry in raw:
        when = entry.get("when")
        action = entry.get("action")
        if not when or not action:
            continue
        params = {k: v for k, v in entry.items() if k not in ("when", "action")}
        jobs.append(ScheduledJob(when=when, action=action, params=params))
    return jobs
