"""DirecTV receiver routes — tune, keypress, status of the 8 boxes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..drivers.directv import DirectvClient, DirectvError


router = APIRouter(prefix="/api/boxes", tags=["boxes"])


def _receivers(request: Request) -> list[dict]:
    return request.app.state.registry.receivers


def _box(request: Request, num: int) -> dict:
    for r in _receivers(request):
        if int(r.get("num", 0)) == num:
            return r
    raise HTTPException(404, f"unknown box {num}")


@router.get("")
async def list_boxes(request: Request) -> list[dict]:
    out = []
    for r in _receivers(request):
        out.append({
            "num": r["num"],
            "name": r.get("name"),
            "host": r["host"],
            "rf": r.get("rf"),
        })
    return out


@router.get("/{num}/tuned")
async def tuned(num: int, request: Request) -> dict:
    box = _box(request, num)
    client = DirectvClient(box["host"])
    try:
        return await client.tuned()
    except DirectvError as exc:
        raise HTTPException(502, str(exc))


@router.post("/{num}/tune")
async def tune(num: int, channel: str, request: Request) -> dict:
    """`channel` accepts 'NNN' or 'NNN.MM'."""
    box = _box(request, num)
    major_s, _, minor_s = channel.partition(".")
    try:
        major = int(major_s)
        minor = int(minor_s) if minor_s else None
    except ValueError:
        raise HTTPException(400, f"bad channel: {channel!r}")
    client = DirectvClient(box["host"])
    try:
        await client.tune(major, minor)
    except DirectvError as exc:
        raise HTTPException(502, str(exc))
    return {"ok": True}


@router.post("/{num}/key/{key}")
async def keypress(num: int, key: str, request: Request) -> dict:
    box = _box(request, num)
    client = DirectvClient(box["host"])
    try:
        await client.keypress(key)
    except DirectvError as exc:
        raise HTTPException(502, str(exc))
    return {"ok": True}
