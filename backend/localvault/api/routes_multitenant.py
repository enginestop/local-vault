from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict
from .. import errors
from ..api.deps import require_user
from ..database.pool import get_pool
from ..services.multitenant_service import list_vaults, create_personal, assert_member, ensure_user_vaults, rotate_wrapped_key

router = APIRouter()

class VaultCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "Personal Vault"

class MembershipCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str

async def admin_user(request: Request):
    user = await require_user(request)
    if user.role != "superadmin":
        raise errors.Forbidden("Only Superadmin can perform this action")
    return user

def user_json(row):
    return {"id": str(row["id"]), "username": row["username"], "email": row["email"], "display_name": row["display_name"], "role": row["role"], "status": row["account_status"], "created_at": row["created_at"].isoformat()}

@router.get("/admin/users")
async def users(request: Request):
    await admin_user(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id,username,email,display_name,role,account_status,created_at FROM users ORDER BY created_at")
    return {"items": [user_json(row) for row in rows]}

@router.post("/admin/users/{user_id}/approve")
async def approve(request: Request, user_id: str):
    actor = await admin_user(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE users SET account_status='active', approved_at=now(), approved_by=$1::uuid WHERE id=$2::uuid AND account_status='pending' RETURNING id,username,email,display_name,role,account_status,created_at", actor.id, user_id)
    if row is None: raise errors.NotFoundError("Pending user not found")
    return user_json(row)

@router.post("/admin/users/{user_id}/reject")
async def reject(request: Request, user_id: str):
    await admin_user(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        deleted = await conn.execute("DELETE FROM users WHERE id=$1::uuid AND account_status='pending'", user_id)
    if deleted.endswith("0"): raise errors.NotFoundError("Pending user not found")
    return {"rejected": True}

@router.post("/admin/users/{user_id}/status")
async def set_status(request: Request, user_id: str, body: dict):
    actor = await admin_user(request)
    value = body.get("status")
    if value not in {"active", "disabled"}: raise errors.ValidationError("status must be active or disabled")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE users SET account_status=$1 WHERE id=$2::uuid RETURNING id,username,email,display_name,role,account_status,created_at", value, user_id)
    if row is None: raise errors.NotFoundError("User not found")
    if value == "disabled": request.app.state.ctx.sessions.lock_user(user_id)
    return user_json(row)

@router.put("/admin/users/{user_id}/role")
async def set_role(request: Request, user_id: str, body: dict):
    actor = await admin_user(request)
    role = body.get("role")
    if role not in {"superadmin", "admin_user"}: raise errors.ValidationError("role must be superadmin or admin_user")
    if actor.id == user_id and role != "superadmin": raise errors.Forbidden("Superadmin cannot remove its own role")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("UPDATE users SET role=$1 WHERE id=$2::uuid RETURNING id,username,email,display_name,role,account_status,created_at", role, user_id)
    if row is None: raise errors.NotFoundError("User not found")
    return user_json(row)

@router.get("/vaults")
async def vaults(request: Request):
    user = await require_user(request)
    return {"items": await list_vaults(user.id, user.role == "superadmin")}

@router.post("/vaults/personal")
async def personal(request: Request, body: VaultCreate):
    user = await require_user(request)
    token = request.headers.get("x-master-password")
    if not token: raise errors.ReauthRequired()
    return await create_personal(user.id, body.name, token)

@router.get("/vaults/{vault_id}/members")
async def members(request: Request, vault_id: str):
    user = await require_user(request)
    await assert_member(user.id, vault_id, user.role == "superadmin")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT u.id,u.username,u.email,vm.active FROM vault_members vm JOIN users u ON u.id=vm.user_id WHERE vm.vault_id=$1::uuid", vault_id)
    return {"items": [dict(row) for row in rows]}

@router.post("/vaults/{vault_id}/members")
async def add_member(request: Request, vault_id: str, body: MembershipCreate):
    actor = await admin_user(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM vaults WHERE id=$1::uuid", vault_id)
        if not exists: raise errors.NotFoundError("Vault not found")
        await conn.execute("INSERT INTO vault_members(vault_id,user_id) VALUES($1::uuid,$2::uuid) ON CONFLICT(vault_id,user_id) DO UPDATE SET active=true", vault_id, body.user_id)
    return {"granted": True}

@router.delete("/vaults/{vault_id}/members/{user_id}")
async def remove_member(request: Request, vault_id: str, user_id: str):
    await admin_user(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM vault_key_wrappings WHERE vault_id=$1::uuid AND user_id=$2::uuid", vault_id, user_id)
        result = await conn.execute("DELETE FROM vault_members WHERE vault_id=$1::uuid AND user_id=$2::uuid", vault_id, user_id)
    if result.endswith("0"): raise errors.NotFoundError("Membership not found")
    request.app.state.ctx.sessions.lock_user(user_id)
    return {"revoked": True}

@router.post("/vaults/{vault_id}/members/{user_id}/wrapped-key/rotate")
async def rotate_key(request: Request, vault_id: str, user_id: str):
    await admin_user(request)
    password = request.headers.get("x-master-password")
    if not password: raise errors.ReauthRequired()
    await rotate_wrapped_key(vault_id, user_id, password)
    return {"rotated": True}
