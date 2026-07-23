import asyncio
import os
import socket
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from .app_context import build_context, AppContext
from .database.pool import create_pool, close_pool
from . import errors
from .logging_setup import make_logger
from .api import (
    routes_status,
    routes_session,
    routes_users,
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

PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
TRUSTED_PROXIES = os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1")


def create_app(data_dir: str, control=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await create_pool()
        ctx = await build_context(data_dir)
        app.state.ctx = ctx
        app.state.control = control
        yield
        await close_pool()
        try:
            ctx.sessions.lock_all()
        except Exception:
            pass

    app = FastAPI(title="LocalVault", version="2.0.0", lifespan=lifespan)

    if PUBLIC_URL:
        parsed = urlparse(PUBLIC_URL)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[origin],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[],
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
                parsed = urlparse(origin)
                if parsed.scheme != request.url.scheme or parsed.netloc.lower() != host.lower():
                    if PUBLIC_URL and parsed.geturl().rstrip("/") == PUBLIC_URL:
                        pass
                    else:
                        response = errors.problem_response(
                            request,
                            errors.ProblemError("ORIGIN_NOT_ALLOWED", "Origin not allowed", "The request origin is not allowed.", 403),
                        )
                        return _secure(response, request.state.request_id)
            # ASGI permits repeated headers and some clients/proxies preserve a
            # stale value alongside the actual one.  Treat the largest declared
            # length as authoritative so a large request cannot be hidden by a
            # smaller duplicate header before FastAPI parses its body.
            content_lengths = [
                value
                for name, value in request.scope.get("headers", [])
                if name.lower() == b"content-length"
            ]
            request_limit = _request_limit(request.url.path)
            if content_lengths:
                try:
                    declared_lengths = [int(value) for value in content_lengths]
                    too_large = max(declared_lengths) > request_limit
                except (TypeError, ValueError):
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

    v1 = "/api/v1"
    app.include_router(routes_status.router, prefix=v1)
    app.include_router(routes_session.router, prefix=v1)
    app.include_router(routes_users.router, prefix=v1)
    app.include_router(routes_credentials.router, prefix=v1)
    app.include_router(routes_categories.router, prefix=v1)
    app.include_router(routes_generator.router, prefix=v1)
    app.include_router(routes_imports.router, prefix=v1)
    app.include_router(routes_exports.router, prefix=v1)
    app.include_router(routes_backups.router, prefix=v1)
    app.include_router(routes_settings.router, prefix=v1)
    app.include_router(routes_trash.router, prefix=v1)
    app.include_router(routes_events.router)

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
    if path.startswith("/api/v1/imports/previews") or path == "/api/v1/backups/restore":
        return 52 * 1024 * 1024
    return 1 * 1024 * 1024


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
    if PUBLIC_URL:
        parsed = urlparse(PUBLIC_URL)
        pub_host = parsed.hostname
        if pub_host:
            hosts.add(pub_host.lower())
    return hosts
