"""FastAPI entry point. Loads registry + code library, mounts API + SPA."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import boxes, health, scenes, tvs
from .auth import AuthMiddleware, router as auth_router
from .codes.library import CodeLibrary
from .config import settings
from .dispatcher import Dispatcher
from . import registry as registry_mod
from .registry import Pairings
from .scheduler import Scheduler, load_jobs
from .status import StatusMonitor


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tvir")


@asynccontextmanager
async def lifespan(app: FastAPI):
    reg = registry_mod.load(settings.config_path)
    codes = CodeLibrary(settings.irdb_path)
    pairings = Pairings(settings.data_path / "pairings.json")
    adb_key = settings.data_path / "adb_key"

    dispatcher = Dispatcher(
        reg, codes, pairings,
        adb_key_path=adb_key,
        timeout=settings.request_timeout_s,
    )
    monitor = StatusMonitor(reg)
    monitor.set_pairings(pairings)
    dispatcher.set_monitor(monitor)
    scheduler = Scheduler(load_jobs(reg.schedule), dispatcher, reg)

    app.state.registry = reg
    app.state.codes = codes
    app.state.pairings = pairings
    app.state.dispatcher = dispatcher
    app.state.status_monitor = monitor
    app.state.scheduler = scheduler

    await monitor.start()
    await scheduler.start()
    log.info("startup complete: %d TVs, %d events, %d schedule jobs",
             len(reg.tvs), len(reg.events), len(reg.schedule))
    try:
        yield
    finally:
        await scheduler.stop()
        await monitor.stop()


app = FastAPI(title="TV-IR", version="0.2.0", lifespan=lifespan)
app.add_middleware(AuthMiddleware)

app.include_router(health.router)
app.include_router(auth_router)
app.include_router(tvs.router)
app.include_router(scenes.router)
app.include_router(boxes.router)


# Serve the built SPA. Multi-stage Dockerfile copies the Vite build output
# into /app/static. SPA fallback lets client-side routes work.
_static = settings.static_path
if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/manifest.webmanifest")
    async def manifest() -> FileResponse:
        return FileResponse(_static / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        return FileResponse(_static / "sw.js", media_type="application/javascript")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        # Don't serve the SPA shell for unmatched /api/* paths — a typo'd API
        # route should 404 as JSON, not return HTML the frontend can't parse.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(_static / "index.html")
