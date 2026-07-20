import asyncio
import os
import socket
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .app_context import build_context, AppContext
from . import errors
from .logging_setup import make_logger
from .api import (
    routes_status,
    routes_session,
    routes_credentials,
    routes_categories,
    routes_generator,
    routes_imports,
    routes_exports,
    routes_backups,
    routes_settings,
    routes_trash,
    routes_events,
)

logger = make_logger("localvault.api", "INFO")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self' ws:; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
    "Cache-Control": "no-store",
}


def create_app(data_dir: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = build_context(data_dir)
        app.state.ctx = ctx
        # scheduler: purge trash + daily not strictly needed here; run purge at startup
        _purge_expired_trash(ctx)
        maintenance = asyncio.create_task(_maintenance_loop(ctx))
        yield
        maintenance.cancel()
        try:
            await maintenance
        except asyncio.CancelledError:
            pass
        try:
            ctx.conn.close()
        except Exception:
            pass

    app = FastAPI(title="LocalVault", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],  # SEC-024: no CORS
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=sorted(_allowed_hosts()),
        www_redirect=False,
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(errors.ProblemError)
    async def problem_handler(request: Request, exc: errors.ProblemError):
        return errors.problem_response(request, exc)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        # SEC-028: do not log secret content; log sanitized
        logger.error("unhandled %s %s %s", request.method, request.url.path, type(exc).__name__, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "type": "https://localvault.app/problems/INTERNAL_ERROR",
                "title": "Internal error",
                "status": 500,
                "code": "INTERNAL_ERROR",
                "detail": "An unexpected error occurred.",
                "request_id": rid,
            },
            headers={"Cache-Control": "no-store", "X-Request-ID": rid},
        )

    # routes
    v1 = "/api/v1"
    app.include_router(routes_status.router, prefix=v1)
    app.include_router(routes_session.router, prefix=v1)
    app.include_router(routes_credentials.router, prefix=v1)
    app.include_router(routes_categories.router, prefix=v1)
    app.include_router(routes_generator.router, prefix=v1)
    app.include_router(routes_imports.router, prefix=v1)
    app.include_router(routes_exports.router, prefix=v1)
    app.include_router(routes_backups.router, prefix=v1)
    app.include_router(routes_settings.router, prefix=v1)
    app.include_router(routes_trash.router, prefix=v1)
    app.include_router(routes_events.router)

    # static SPA
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets"), html=False), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not Found"})
            index = os.path.join(static_dir, "index.html")
            return FileResponse(index)

    return app


def _allowed_hosts() -> set[str]:
    hosts = {"127.0.0.1", "localhost", "::1"}
    hostname = socket.gethostname()
    if hostname:
        hosts.add(hostname.lower())
    fqdn = socket.getfqdn()
    if fqdn:
        hosts.add(fqdn.lower())
    try:
        for info in socket.getaddrinfo(hostname, None):
            address = info[4][0].split("%", 1)[0]
            if address:
                hosts.add(address.lower())
    except OSError:
        pass
    return hosts


async def _maintenance_loop(ctx: AppContext) -> None:
    while True:
        await asyncio.sleep(1)
        removed = ctx.sessions.cleanup_expired()
        await ctx.imports.cleanup(ctx.sessions.active_session_ids())
        if removed and not ctx.sessions.has_sessions() and ctx.vault.is_unlocked():
            ctx.vault.lock_all()


def _purge_expired_trash(ctx: AppContext) -> None:
    if not ctx.vault.setup_completed:
        return
    # We cannot decrypt without unlock; trash purge happens after unlock in app.
    # This startup hook only runs when already unlocked is impossible; skip.
    return
