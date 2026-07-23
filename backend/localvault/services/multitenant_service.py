import uuid
import os
from hashlib import sha256

from ..crypto.aes import aes_gcm_decrypt, aes_gcm_encrypt
from ..crypto.csprng import random_bytes
from ..crypto.kdf import derive_kek, new_salt
from ..database.pool import get_pool
from .. import errors


def _wrap(dek: bytes, password: str) -> tuple[bytes, bytes, bytes]:
    salt = new_salt()
    nonce = random_bytes(12)
    return salt, nonce, aes_gcm_encrypt(derive_kek(password, salt), nonce, dek, b"LocalVault|vault-dek|1")

def _server_key() -> bytes:
    return sha256(os.environ.get("LOCALVAULT_SECRET", "localvault-development-secret").encode()).digest()

def _seal(dek: bytes, nonce: bytes) -> bytes:
    return aes_gcm_encrypt(_server_key(), nonce, dek, b"LocalVault|server-sealed-dek|1")

def _unseal(ciphertext: bytes, nonce: bytes) -> bytes:
    return aes_gcm_decrypt(_server_key(), nonce, ciphertext, b"LocalVault|server-sealed-dek|1")


async def ensure_user_vaults(user_id: str, master_password: str, language: str = "id") -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        shared = await conn.fetchrow("SELECT id FROM vaults WHERE kind='shared' LIMIT 1")
        if shared is None:
            shared_id = uuid.uuid4()
            await conn.execute("INSERT INTO vaults(id, name, kind) VALUES($1, 'Shared Vault', 'shared')", shared_id)
            shared = {"id": shared_id}
        personal = await conn.fetchrow("SELECT id FROM vaults WHERE kind='personal' AND owner_id=$1::uuid", user_id)
        if personal is None:
            personal_id = uuid.uuid4()
            await conn.execute("INSERT INTO vaults(id, name, kind, owner_id) VALUES($1, $2, 'personal', $3::uuid)", personal_id, f"Personal Vault", user_id)
            personal = {"id": personal_id}
        for vault_id in (shared["id"], personal["id"]):
            await conn.execute("INSERT INTO vault_members(vault_id,user_id) VALUES($1,$2::uuid) ON CONFLICT DO NOTHING", vault_id, user_id)
            sealed = await conn.fetchval("SELECT dek_ciphertext FROM vaults WHERE id=$1", vault_id)
            nonce = await conn.fetchval("SELECT dek_nonce FROM vaults WHERE id=$1", vault_id)
            if sealed is None:
                dek = random_bytes(32); nonce = random_bytes(12)
                await conn.execute("UPDATE vaults SET dek_ciphertext=$1, dek_nonce=$2 WHERE id=$3", _seal(dek, nonce), nonce, vault_id)
            else:
                dek = _unseal(sealed, nonce)
            salt, nonce, wrapped = _wrap(dek, master_password)
            await conn.execute("""INSERT INTO vault_key_wrappings(vault_id,user_id,kek_salt,wrapped_dek,wrap_nonce)
                VALUES($1,$2::uuid,$3,$4,$5) ON CONFLICT(vault_id,user_id) DO UPDATE SET kek_salt=excluded.kek_salt, wrapped_dek=excluded.wrapped_dek, wrap_nonce=excluded.wrap_nonce""", vault_id, user_id, salt, wrapped, nonce)


async def list_vaults(user_id: str, is_superadmin: bool = False) -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT v.id,v.name,v.kind,v.owner_id,v.revision,vm.active,
            (v.owner_id=$1::uuid) AS owned FROM vaults v JOIN vault_members vm ON vm.vault_id=v.id
            WHERE vm.user_id=$1::uuid AND vm.active ORDER BY v.kind, v.name""", user_id)
        if is_superadmin:
            rows = await conn.fetch("SELECT id,name,kind,owner_id,revision,true AS active,(owner_id=$1::uuid) AS owned FROM vaults ORDER BY kind,name", user_id)
    return [dict(row) for row in rows]


async def create_personal(user_id: str, name: str, master_password: str) -> dict:
    pool = get_pool()
    vault_id = uuid.uuid4()
    dek = random_bytes(32)
    server_nonce = random_bytes(12)
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO vaults(id,name,kind,owner_id,dek_ciphertext,dek_nonce) VALUES($1,$2,'personal',$3::uuid,$4,$5)", vault_id, name.strip() or "Personal Vault", user_id, _seal(dek, server_nonce), server_nonce)
        await conn.execute("INSERT INTO vault_members(vault_id,user_id) VALUES($1,$2::uuid)", vault_id, user_id)
        salt, nonce, wrapped = _wrap(dek, master_password)
        await conn.execute("INSERT INTO vault_key_wrappings(vault_id,user_id,kek_salt,wrapped_dek,wrap_nonce) VALUES($1,$2::uuid,$3,$4,$5)", vault_id, user_id, salt, wrapped, nonce)
    return {"id": str(vault_id), "name": name.strip() or "Personal Vault", "kind": "personal", "owner_id": user_id, "revision": 1, "active": True, "owned": True}


async def assert_member(user_id: str, vault_id: str, is_superadmin: bool = False) -> None:
    if is_superadmin:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        ok = await conn.fetchval("SELECT 1 FROM vault_members WHERE vault_id=$1::uuid AND user_id=$2::uuid AND active", vault_id, user_id)
    if not ok:
        raise errors.Forbidden("Vault access is not granted")

async def rotate_wrapped_key(vault_id: str, user_id: str, master_password: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT dek_ciphertext,dek_nonce FROM vaults WHERE id=$1::uuid", vault_id)
        if row is None: raise errors.NotFoundError("Vault not found")
        member = await conn.fetchval("SELECT 1 FROM vault_members WHERE vault_id=$1::uuid AND user_id=$2::uuid AND active", vault_id, user_id)
        if not member: raise errors.Forbidden("Vault membership is not active")
        dek = _unseal(row["dek_ciphertext"], row["dek_nonce"])
        salt, nonce, wrapped = _wrap(dek, master_password)
        await conn.execute("""INSERT INTO vault_key_wrappings(vault_id,user_id,kek_salt,wrapped_dek,wrap_nonce)
            VALUES($1::uuid,$2::uuid,$3,$4,$5) ON CONFLICT(vault_id,user_id) DO UPDATE SET kek_salt=excluded.kek_salt,wrapped_dek=excluded.wrapped_dek,wrap_nonce=excluded.wrap_nonce""", vault_id, user_id, salt, wrapped, nonce)
