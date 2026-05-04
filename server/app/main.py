"""FastAPI entry point. Loads registry + code library, mounts API + SPA."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import health, scenes, tvs
from .codes.library import CodeLibrary
from .config import settings
from .dispatcher import Dispatcher
from . import registry as registry_mod


@asynccontextmanager
async def lifespan(app: FastAPI):
    reg = registry_mod.load(settings.config_path)
    codes = CodeLibrary(settings.irdb_path)
    app.state.registry = reg
    app.state.codes = codes
    app.state.dispatcher = Dispatcher(reg, codes, timeout=settings.request_timeout_s)
    yield


app = FastAPI(title="TV-IR", version="0.1.0", lifespan=lifespan)

app.include_router(health.router)
app.include_router(tvs.router)
app.include_router(scenes.router)


# Serve the built SPA. The Dockerfile copies the Vite build output into
# /app/static. Falling back to index.html lets client-side routes work.
_static = settings.static_path
if _static.is_dir():
    app.mount("/assets", StaticFiles(directory=_static / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        index = _static / "index.html"
        return FileResponse(index)
