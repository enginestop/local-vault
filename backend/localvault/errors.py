from typing import Optional

from fastapi import Request, status
from fastapi.responses import JSONResponse
import uuid


class ProblemError(Exception):
    def __init__(
        self,
        code: str,
        title: str,
        detail: str,
        status_code: int = 400,
        errors: Optional[list] = None,
    ) -> None:
        self.code = code
        self.title = title
        self.detail = detail
        self.status_code = status_code
        self.errors = errors
        super().__init__(detail)


class SetupAlreadyCompleted(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            "SETUP_ALREADY_COMPLETED",
            "Setup already completed",
            "Vault has already been set up.",
            status_code=status.HTTP_409_CONFLICT,
        )


class SessionInvalid(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            "SESSION_INVALID",
            "Session invalid",
            "The session token is invalid or expired.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ReauthRequired(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            "REAUTH_REQUIRED",
            "Reauthentication required",
            "A valid master password is required for this action.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class VaultLocked(ProblemError):
    def __init__(self) -> None:
        super().__init__(
            "VAULT_LOCKED",
            "Vault locked",
            "The vault is locked.",
            status_code=status.HTTP_423_LOCKED,
        )


class RevisionConflict(ProblemError):
    def __init__(self, current_revision: int) -> None:
        super().__init__(
            "REVISION_CONFLICT",
            "Revision conflict",
            "The item was modified by another session.",
            status_code=status.HTTP_409_CONFLICT,
            errors=[{"current_revision": current_revision}],
        )


class ValidationError(ProblemError):
    def __init__(self, detail: str, errors: Optional[list] = None) -> None:
        super().__init__(
            "VALIDATION_ERROR",
            "Validation error",
            detail,
            status_code=422,
            errors=errors,
        )


class NotFoundError(ProblemError):
    def __init__(self, detail: str = "Resource not found") -> None:
        super().__init__(
            "NOT_FOUND",
            "Not found",
            detail,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictError(ProblemError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, "Conflict", detail, status_code=status.HTTP_409_CONFLICT)


class StorageError(ProblemError):
    def __init__(self, detail: str = "Storage or backup operation failed") -> None:
        super().__init__(
            "STORAGE_FAILED",
            "Storage failed",
            detail,
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        )


class PreconditionRequired(ProblemError):
    def __init__(self, detail: str = "If-Match header required") -> None:
        super().__init__(
            "PRECONDITION_REQUIRED",
            "Precondition required",
            detail,
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        )


def problem_response(request: Request, exc: ProblemError) -> JSONResponse:
    rid = getattr(request.state, "request_id", str(uuid.uuid4()))
    body = {
        "type": f"https://localvault.app/problems/{exc.code.lower()}",
        "title": exc.title,
        "status": exc.status_code,
        "code": exc.code,
        "detail": exc.detail,
        "request_id": rid,
    }
    if exc.errors is not None:
        body["errors"] = exc.errors
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers={"Cache-Control": "no-store", "X-Request-ID": rid},
    )
