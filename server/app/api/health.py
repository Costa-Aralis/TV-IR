"""Health endpoint for the LXC / Docker healthcheck."""

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health() -> dict:
    return {"ok": True}
