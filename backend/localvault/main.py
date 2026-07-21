import asyncio
import os
import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

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
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
    "Cache-Control": "no-store",
}


def create_app(data_dir: str, control=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        ctx = build_context(data_dir, control=control)
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
    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        request.state.request_id = _request_id(request.headers.get("x-request-id"))
        if request.url.path.startswith("/api/"):
            host = request.headers.get("host", "")
            hostname = host.rsplit(":", 1)[0].strip("[]").lower()
            if hostname not in _allowed_hosts():
                response = errors.problem_response(
                    request,
                    errors.ProblemError("HOST_NOT_ALLOWED", "Host not allowed", "The Host header is not allowed.", 400),
                )
                return _secure(response, request.state.request_id)
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != request.url.scheme or parsed.netloc.lower() != host.lower():
                    response = errors.problem_response(
                        request,
                        errors.ProblemError("ORIGIN_NOT_ALLOWED", "Origin not allowed", "The request origin is not allowed.", 403),
                    )
                    return _secure(response, request.state.request_id)
            content_length = request.headers.get("content-length")
            request_limit = _request_limit(request.url.path)
            if content_length:
                try:
                    too_large = int(content_length) > request_limit
                except ValueError:
                    too_large = True
                if too_large:
                    response = errors.problem_response(
                        request,
                        errors.ProblemError("REQUEST_TOO_LARGE", "Request too large", "The request exceeds the allowed size.", 413),
                    )
                    return _secure(response, request.state.request_id)
            if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > request_limit:
                        response = errors.problem_response(
                            request,
                            errors.ProblemError("REQUEST_TOO_LARGE", "Request too large", "The request exceeds the allowed size.", 413),
                        )
                        return _secure(response, request.state.request_id)
                # Starlette's wrapped receive replays a cached body to the
                # downstream parser, including for chunked requests.
                request._body = bytes(body)
        response = await call_next(request)
        return _secure(response, request.state.request_id)

    @app.exception_handler(errors.ProblemError)
    async def problem_handler(request: Request, exc: errors.ProblemError):
        return errors.problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        safe_errors = [
            {"location": list(item.get("loc", ())), "message": item.get("msg", "Invalid value"), "type": item.get("type", "validation_error")}
            for item in exc.errors()
        ]
        return errors.problem_response(
            request,
            errors.ValidationError("The request failed validation.", safe_errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return errors.problem_response(
            request,
            errors.ProblemError(code, "Not found" if exc.status_code == 404 else "HTTP error", "The requested resource was not found." if exc.status_code == 404 else "The request could not be completed.", exc.status_code),
        )

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
            media_type="application/problem+json",
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
        async def spa(request: Request, full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                return errors.problem_response(
                    request,
                    errors.NotFoundError("The requested API route was not found."),
                )
            index = os.path.join(static_dir, "index.html")
            return FileResponse(index)

    return app


def _request_id(candidate: str | None) -> str:
    try:
        return str(uuid.UUID(candidate)) if candidate else str(uuid.uuid4())
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid4())


def _request_limit(path: str) -> int:
    if path in {"/api/v1/setup", "/api/v1/sessions/unlock", "/api/v1/sessions/recover"}:
        return 1024 * 1024
    if path.startswith("/api/v1/imports/previews") or path == "/api/v1/backups/restore":
        return 52 * 1024 * 1024
    return 2 * 1024 * 1024


def _secure(response: Response, request_id: str) -> Response:
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request_id
    return response


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
