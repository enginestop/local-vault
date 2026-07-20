from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..app_context import AppContext
from .. import errors
from ..api.deps import require_session
from ..crypto.password_gen import generate, GeneratorError
from ..domain.models import strength_of

router = APIRouter()


class GeneratorRequest(BaseModel):
    length: int = 20
    include_lowercase: bool = True
    include_uppercase: bool = True
    include_digits: bool = True
    include_symbols: bool = True
    exclude_ambiguous: bool = False


@router.post("/password-generator")
async def password_generator(request: Request, body: GeneratorRequest) -> dict:
    require_session(request)
    try:
        pw = generate(
            body.length,
            body.include_lowercase,
            body.include_uppercase,
            body.include_digits,
            body.include_symbols,
            body.exclude_ambiguous,
        )
    except GeneratorError as e:
        raise errors.ValidationError(str(e))
    # GEN-005: not logged, Cache-Control no-store
    return {"password": pw, "strength": strength_of(pw)}
