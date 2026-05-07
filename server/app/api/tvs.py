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
async def list_tvs(request: Request) -> dict:
    registry = request.app.state.registry
    return {
        "presets": _presets_payload(registry),
        "tvs": [
            {
                "id": tv.id,
                "name": tv.name,
                "slot": tv.slot,
                "type": tv.type,
            }
            for tv in sorted(registry.tvs, key=lambda t: t.slot)
        ],
    }


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
        "presets": _presets_payload(registry),
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
def _presets_payload(registry) -> list[dict]:
    """Return the list of presets with channel labels and the RF digits used.

    Preset numbers come from the union of preset_template and any per-TV
    overrides. Labels fall back to "Box N" if not configured.
    """
    keys: set[str] = set(registry.preset_template.keys())
    for tv in registry.tvs:
        if tv.presets:
            keys.update(tv.presets.keys())
    nums = sorted(int(k) for k in keys if k.isdigit())
    out = []
    for n in nums:
        key = str(n)
        seq = registry.preset_template.get(key, [])
        rf = _rf_from_sequence(seq)
        out.append({
            "num": n,
            "label": registry.preset_labels.get(key, f"Box {n}"),
            "rf": rf,
        })
    return out


def _rf_from_sequence(seq) -> str | None:
    """Reconstruct the RF channel ('30.2') from a digit sequence for display."""
    digits: list[str] = []
    saw_dot = False
    for step in seq:
        if isinstance(step, dict):
            continue
        if step in {"Enter", "Ok"}:
            break
        if step in {"Dot", "Dash"}:
            digits.append(".")
            saw_dot = True
            continue
        if step.isdigit():
            digits.append(step)
    if not digits:
        return None
    return "".join(digits) if saw_dot else "".join(digits)


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
