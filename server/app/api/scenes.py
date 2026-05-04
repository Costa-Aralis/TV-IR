"""Scene routes: bulk operations across all TVs."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request


router = APIRouter(prefix="/api/scenes", tags=["scenes"])


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


async def _broadcast(request: Request, action) -> dict:
    registry = request.app.state.registry
    dispatcher = request.app.state.dispatcher

    async def run(tv) -> tuple[str, str | None]:
        try:
            await action(dispatcher, tv)
            return tv.id, None
        except Exception as exc:  # noqa: BLE001
            return tv.id, str(exc)

    results = await asyncio.gather(*(run(tv) for tv in registry.tvs))
    failures = {tv_id: err for tv_id, err in results if err}
    return {"ok": not failures, "failed": failures}
