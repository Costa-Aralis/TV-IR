"""TV control routes: power, presets, arbitrary keys."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/tvs", tags=["tvs"])


class PowerRequest(BaseModel):
    state: Literal["on", "off", "toggle"] = "toggle"


class KeyRequest(BaseModel):
    key: str = Field(min_length=1)


@router.get("")
async def list_tvs(request: Request) -> list[dict]:
    registry = request.app.state.registry
    return [
        {
            "id": tv.id,
            "name": tv.name,
            "slot": tv.slot,
            "type": tv.type,
            "presets": _preset_keys(registry, tv),
        }
        for tv in sorted(registry.tvs, key=lambda t: t.slot)
    ]


@router.get("/{tv_id}")
async def get_tv(tv_id: str, request: Request) -> dict:
    registry = request.app.state.registry
    try:
        tv = registry.get(tv_id)
    except KeyError:
        raise HTTPException(404, f"unknown tv: {tv_id}")
    return {
        "id": tv.id,
        "name": tv.name,
        "slot": tv.slot,
        "type": tv.type,
        "url": tv.url,
        "codes": tv.codes,
        "presets": _preset_keys(registry, tv),
    }


@router.post("/{tv_id}/power")
async def power(tv_id: str, body: PowerRequest, request: Request) -> dict:
    return await _dispatch(request, lambda d: d.power(tv_id, body.state))


@router.post("/{tv_id}/preset/{preset_num}")
async def preset(tv_id: str, preset_num: int, request: Request) -> dict:
    if not 1 <= preset_num <= 8:
        raise HTTPException(400, "preset must be 1..8")
    return await _dispatch(request, lambda d: d.preset(tv_id, preset_num))


@router.post("/{tv_id}/key")
async def key(tv_id: str, body: KeyRequest, request: Request) -> dict:
    return await _dispatch(request, lambda d: d.key(tv_id, body.key))


# ---- internals ----
def _preset_keys(registry, tv) -> list[int]:
    keys = set((tv.presets or {}).keys()) | set(registry.preset_template.keys())
    return sorted(int(k) for k in keys if k.isdigit())


async def _dispatch(request: Request, action) -> dict:
    dispatcher = request.app.state.dispatcher
    from ..dispatcher import DispatchError
    try:
        await action(dispatcher)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except DispatchError as exc:
        raise HTTPException(502, str(exc))
    return {"ok": True}
