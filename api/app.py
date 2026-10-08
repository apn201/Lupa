"""FastAPI app: the proposed API, the PayPal routes, the static UI, the expiry worker."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import MARKERS, ROOT, settings_from_env
from ..service import Lupa, LupaError
from . import paypal_routes, proposed

log = logging.getLogger("lupa")
WEB = ROOT / "web"


def create_app(lupa: Lupa | None = None, *, workers: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "lupa", None) is None:
            app.state.lupa = Lupa(settings_from_env())
        task = asyncio.create_task(_expiry_loop(app)) if workers else None
        yield
        if task:
            task.cancel()

    app = FastAPI(
        title="Lupa - Consumer Payment Authorization API (proposed)",
        version="0.1.0",
        description=(
            "◇ endpoints under /proposed/v1/me are proposed; PayPal has no such API today. "
            "● routes under /paypal call the PayPal sandbox. ◆ marks AI interpretation, "
            "■ deterministic policy enforcement. Amounts are integer minor units."
        ),
        lifespan=lifespan,
    )
    app.state.lupa = lupa

    @app.exception_handler(LupaError)
    async def lupa_error(_: Request, exc: LupaError):
        body = {"error": {"code": exc.code, "message": exc.message, **exc.extra}}
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError):
        code = "policy_invalid" if "/polic" in str(_.url.path) else "invalid_request"
        return JSONResponse({"error": {"code": code, "message": "invalid body",
                                       "details": exc.errors()}}, status_code=422)

    app.include_router(proposed.router)
    app.include_router(paypal_routes.router)

    @app.get("/api/markers", tags=["ui"])
    def markers():
        return MARKERS

    if WEB.exists():
        app.mount("/static", StaticFiles(directory=WEB), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(WEB / "index.html")

    return app


async def _expiry_loop(app: FastAPI, every: float = 60.0) -> None:
    while True:
        try:
            await asyncio.sleep(every)
            expired = await asyncio.to_thread(app.state.lupa.expire_holds)
            if expired:
                log.info("expired holds: %s", expired)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the worker must not die on one bad row
            log.warning("expiry worker: %s", exc)


app = create_app()
