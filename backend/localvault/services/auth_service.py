import uuid
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

from ..database.pool import get_pool
from .. import errors

_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


class User:
    def __init__(
        self,
        id: str,
        username: str,
        email: str,
        display_name: str,
        recovery_enabled: bool,
        created_at: str,
    ) -> None:
        self.id = id
        self.username = username
        self.email = email
        self.display_name = display_name
        self.recovery_enabled = recovery_enabled
        self.created_at = created_at


async def register(
    username: str,
    email: str,
    master_password: str,
) -> User:
    pool = get_pool()
    user_id = str(uuid.uuid4())
    password_hash = _ph.hash(master_password)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (id, username, email, master_password_hash)
                VALUES ($1, $2, $3, $4)
                RETURNING id, username, email, display_name, recovery_enabled, created_at
                """,
                user_id, username, email, password_hash,
            )
        except Exception as ex:
            pgcode = getattr(ex, "pgcode", "")
            if pgcode == "23505":
                detail = str(ex)
                if "users_username" in detail or "idx_users_username" in detail:
                    raise errors.ConflictError("USERNAME_TAKEN", "Username already taken")
                raise errors.ConflictError("EMAIL_TAKEN", "Email already taken")
            raise
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        display_name=row["display_name"],
        recovery_enabled=row["recovery_enabled"],
        created_at=row["created_at"].isoformat(),
    )


async def authenticate(login: str, master_password: str) -> User:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, email, display_name, recovery_enabled,
                   created_at, master_password_hash
            FROM users
            WHERE lower(username) = lower($1) OR lower(email) = lower($1)
            """,
            login,
        )
    if row is None:
        raise errors.ProblemError(
            "LOGIN_FAILED", "Login failed",
            "Invalid username/email or master password", 401,
        )
    try:
        _ph.verify(row["master_password_hash"], master_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise errors.ProblemError(
            "LOGIN_FAILED", "Login failed",
            "Invalid username/email or master password", 401,
        )
    if _ph.check_needs_rehash(row["master_password_hash"]):
        new_hash = _ph.hash(master_password)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET master_password_hash = $1 WHERE id = $2",
                new_hash, row["id"],
            )
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        display_name=row["display_name"],
        recovery_enabled=row["recovery_enabled"],
        created_at=row["created_at"].isoformat(),
    )


async def get_user_by_id(user_id: str) -> User | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, username, email, display_name, recovery_enabled, created_at
            FROM users WHERE id = $1::uuid
            """,
            user_id,
        )
    if row is None:
        return None
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        display_name=row["display_name"],
        recovery_enabled=row["recovery_enabled"],
        created_at=row["created_at"].isoformat(),
    )


async def update_profile(
    user_id: str,
    username: str | None = None,
    email: str | None = None,
    display_name: str | None = None,
) -> User:
    pool = get_pool()
    sets = []
    params = []
    idx = 2
    if username is not None:
        sets.append(f"username = ${idx}")
        params.append(username)
        idx += 1
    if email is not None:
        sets.append(f"email = ${idx}")
        params.append(email)
        idx += 1
    if display_name is not None:
        sets.append(f"display_name = ${idx}")
        params.append(display_name)
    if not sets:
        return await get_user_by_id(user_id)
    params.insert(0, user_id)
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                f"""
                UPDATE users SET {', '.join(sets)}, updated_at = now()
                WHERE id = $1::uuid
                RETURNING id, username, email, display_name, recovery_enabled, created_at
                """,
                *params,
            )
        except Exception as ex:
            pgcode = getattr(ex, "pgcode", "")
            if pgcode == "23505":
                detail = str(ex)
                if "users_username" in detail or "idx_users_username" in detail:
                    raise errors.ConflictError("USERNAME_TAKEN", "Username already taken")
                raise errors.ConflictError("EMAIL_TAKEN", "Email already taken")
            raise
    return User(
        id=row["id"],
        username=row["username"],
        email=row["email"],
        display_name=row["display_name"],
        recovery_enabled=row["recovery_enabled"],
        created_at=row["created_at"].isoformat(),
    )


async def change_master_password(
    user_id: str,
    current_password: str,
    new_password: str,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT master_password_hash FROM users WHERE id = $1::uuid",
            user_id,
        )
    if row is None:
        raise errors.NotFoundError("User not found")
    try:
        _ph.verify(row["master_password_hash"], current_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise errors.ProblemError(
            "REAUTH_FAILED", "Reauthentication failed",
            "Current master password is incorrect", 401,
        )
    new_hash = _ph.hash(new_password)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET master_password_hash = $1, password_updated_at = now() WHERE id = $2::uuid",
            new_hash, user_id,
        )


async def set_master_password(user_id: str, new_password: str) -> None:
    pool = get_pool()
    new_hash = _ph.hash(new_password)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET master_password_hash = $1, password_updated_at = now() WHERE id = $2::uuid",
            new_hash, user_id,
        )
