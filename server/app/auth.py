"""Simple PIN-based auth for the tablet UI.

Intent: keep customers from tapping `Close` while still being trivial for
staff to use. Not a security boundary — anyone on the bar's WiFi can sniff
the cookie. Set `TVIR_PIN=1234` in compose to enable; unset to disable.

Flow:
  POST /api/auth/login   {pin: "1234"}  → sets `tvir_session` cookie
  GET  /api/auth/status                  → {authed: bool}
  POST /api/auth/logout                  → clears cookie

Mutating endpoints (POST/PUT/DELETE) require the cookie when PIN is set.
"""

from __future__ import annotations

import hmac
import os
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware


COOKIE_NAME = "tvir_session"
_OPEN_PATHS = {
    "/api/health",
    "/api/auth/login",
    "/api/auth/status",
    "/api/auth/logout",
}
_OPEN_PREFIXES = ("/assets/", "/static/")


def configured_pin() -> str | None:
    pin = os.environ.get("TVIR_PIN", "").strip()
    return pin or None


def _expected_token(pin: str) -> str:
    # Deterministic token tied to the PIN — rotates automatically when PIN changes.
    return hmac.new(
        key=b"tv-ir-session",
        msg=pin.encode(),
        digestmod="sha256",
    ).hexdigest()[:32]


def is_authed(request: Request) -> bool:
    pin = configured_pin()
    if pin is None:
        return True  # no PIN configured → open access
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return False
    return hmac.compare_digest(cookie, _expected_token(pin))


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        pin = configured_pin()
        if pin is None:
            return await call_next(request)

        path = request.url.path
        # Allow GETs to read endpoints + open paths/prefixes
        if request.method == "GET" or path in _OPEN_PATHS:
            return await call_next(request)
        if any(path.startswith(p) for p in _OPEN_PREFIXES):
            return await call_next(request)

        if not is_authed(request):
            return JSONResponse(
                {"ok": False, "error": "auth_required"},
                status_code=401,
            )
        return await call_next(request)


# ---- routes ----
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    pin: str


@router.post("/login")
async def login(body: LoginRequest, response: Response) -> dict:
    pin = configured_pin()
    if pin is None:
        return {"ok": True, "authed": True, "pin_required": False}
    # compare_digest raises on non-ASCII str; compare bytes to be safe.
    if not hmac.compare_digest(body.pin.encode("utf-8"), pin.encode("utf-8")):
        return JSONResponse({"ok": False, "error": "bad_pin"}, status_code=401)
    token = _expected_token(pin)
    # 12-hour cookie, httpOnly, SameSite=Lax for the tablet kiosk on the LAN.
    response.set_cookie(
        COOKIE_NAME, token,
        max_age=12 * 3600, httponly=True, samesite="lax",
    )
    return {"ok": True, "authed": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/status")
async def status(request: Request) -> dict:
    return {
        "pin_required": configured_pin() is not None,
        "authed": is_authed(request),
    }


# Stateless dev-only helper used in tests/CLI.
def make_token_for_pin(pin: str) -> str:
    return _expected_token(pin)
