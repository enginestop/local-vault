from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from ..app_context import AppContext
from ..api.deps import require_user
from ..services.auth_service import update_profile as svc_update_profile, change_master_password as svc_change_master

router = APIRouter()


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str | None = None
    email: str | None = None
    display_name: str | None = None


class ChangeMasterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_master_password: str
    new_master_password: str


class UserProfileResponse(BaseModel):
    id: str
    username: str
    email: str
    display_name: str
    recovery_enabled: bool
    created_at: str
    role: str
    account_status: str


@router.get("/users/me")
async def get_profile(request: Request) -> UserProfileResponse:
    user = await require_user(request)
    return UserProfileResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        display_name=user.display_name,
        recovery_enabled=user.recovery_enabled,
        created_at=user.created_at,
        role=user.role,
        account_status=user.account_status,
    )


@router.put("/users/me")
async def update_profile(request: Request, body: UpdateProfileRequest) -> UserProfileResponse:
    user = await require_user(request)
    updated = await svc_update_profile(
        user.id,
        username=body.username.strip() if body.username else None,
        email=body.email.strip().lower() if body.email else None,
        display_name=body.display_name.strip() if body.display_name else None,
    )
    return UserProfileResponse(
        id=str(updated.id),
        username=updated.username,
        email=updated.email,
        display_name=updated.display_name,
        recovery_enabled=updated.recovery_enabled,
        created_at=updated.created_at,
        role=updated.role,
        account_status=updated.account_status,
    )


@router.put("/users/me/master-password")
async def change_master(request: Request, body: ChangeMasterRequest) -> dict:
    user = await require_user(request)
    await svc_change_master(user.id, body.current_master_password, body.new_master_password)
    return {"changed": True}
