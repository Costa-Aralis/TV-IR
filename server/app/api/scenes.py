"""Scene routes: bulk operations across all TVs, by zone, or via saved events."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(prefix="/api/scenes", tags=["scenes"])


@router.post("/open")
async def open_shift(request: Request) -> dict:
    """All TVs on. Channels are left wherever they were last set."""
    return await _broadcast(request, lambda d, tv: d.power(tv.id, "on"))


@router.post("/close")
async def close_shift(request: Request) -> dict:
    """All TVs off."""
    return await _broadcast(request, lambda d, tv: d.power(tv.id, "off"))


@router.post("/all-off")
async def all_off(request: Request) -> dict:
    return await _broadcast(request, lambda d, tv: d.power(tv.id, "off"))


@router.post("/all-on")
async def all_on(request: Request) -> dict:
    return await _broadcast(request, lambda d, tv: d.power(tv.id, "on"))


@router.post("/all-to-preset/{preset_num}")
async def all_to_preset(preset_num: int, request: Request) -> dict:
    if not 1 <= preset_num <= 8:
        raise HTTPException(400, "preset must be 1..8")
    return await _broadcast(request, lambda d, tv: d.preset(tv.id, preset_num))


# ---- Zone-scoped scenes ----
@router.post("/zone/{zone}/power")
async def zone_power(zone: str, state: str, request: Request) -> dict:
    if state not in ("on", "off"):
        raise HTTPException(400, "state must be on|off")
    return await _broadcast(
        request,
        lambda d, tv: d.power(tv.id, state),
        zone=zone,
    )


@router.post("/zone/{zone}/preset/{preset_num}")
async def zone_preset(zone: str, preset_num: int, request: Request) -> dict:
    if not 1 <= preset_num <= 8:
        raise HTTPException(400, "preset must be 1..8")
    return await _broadcast(
        request,
        lambda d, tv: d.preset(tv.id, preset_num),
        zone=zone,
    )


# ---- Saved events ----
@router.get("/events")
async def list_events(request: Request) -> list[dict]:
    registry = request.app.state.registry
    return [
        {
            "id": ev.id,
            "name": ev.name,
            "description": ev.description,
            "actions": [a.model_dump() for a in ev.actions],
        }
        for ev in registry.events
    ]


@router.post("/events/{event_id}/apply")
async def apply_event(event_id: str, request: Request) -> dict:
    registry = request.app.state.registry
    dispatcher = request.app.state.dispatcher
    event = next((e for e in registry.events if e.id == event_id), None)
    if event is None:
        raise HTTPException(404, f"unknown event: {event_id}")

    async def run_action(action) -> tuple[str, str | None]:
        targets = _resolve_targets(registry, action.target)
        coros = []
        for tv in targets:
            if action.power == "on":
                coros.append(_safe(dispatcher.power(tv.id, "on"), tv.id))
            elif action.power == "off":
                coros.append(_safe(dispatcher.power(tv.id, "off"), tv.id))
            if action.preset:
                coros.append(_safe(dispatcher.preset(tv.id, action.preset), tv.id))
        results = await asyncio.gather(*coros)
        return results

    nested = await asyncio.gather(*(run_action(a) for a in event.actions))
    failed: dict[str, str] = {}
    for inner in nested:
        for tv_id, err in inner:
            if err:
                failed[tv_id] = err
    return {"ok": not failed, "failed": failed}


# ---- internals ----
def _resolve_targets(registry, target: str | list[str]):
    """`target` can be 'all', a zone name, a list of TV ids, or a single id."""
    if target == "all":
        return [tv for tv in registry.tvs if tv.type not in ("tbd", "defective")]
    if isinstance(target, list):
        wanted = set(target)
        return [tv for tv in registry.tvs if tv.id in wanted]
    # match by zone, then by single id
    zone_match = [tv for tv in registry.tvs if tv.zone == target]
    if zone_match:
        return zone_match
    try:
        return [registry.get(target)]
    except KeyError:
        return []


async def _safe(coro, tv_id: str) -> tuple[str, str | None]:
    try:
        await coro
        return tv_id, None
    except Exception as exc:  # noqa: BLE001
        return tv_id, str(exc)


async def _broadcast(request: Request, action, *, zone: str | None = None) -> dict:
    registry = request.app.state.registry
    dispatcher = request.app.state.dispatcher

    targets = [tv for tv in registry.tvs if tv.type not in ("tbd", "defective")]
    if zone is not None:
        targets = [tv for tv in targets if tv.zone == zone]
        if not targets:
            raise HTTPException(404, f"no TVs in zone {zone!r}")

    async def run(tv) -> tuple[str, str | None]:
        try:
            await action(dispatcher, tv)
            return tv.id, None
        except Exception as exc:  # noqa: BLE001
            return tv.id, str(exc)

    results = await asyncio.gather(*(run(tv) for tv in targets))
    failures = {tv_id: err for tv_id, err in results if err}
    return {"ok": not failures, "failed": failures}
