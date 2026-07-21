SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    master_password_hash TEXT NOT NULL,
    password_updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recovery_enabled BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(lower(email));

CREATE TABLE IF NOT EXISTS vault_envelopes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vault_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    vault_revision INTEGER NOT NULL,
    format_version INTEGER NOT NULL,
    kdf_algorithm TEXT NOT NULL,
    kdf_salt BYTEA NOT NULL,
    kdf_m_cost_kib INTEGER NOT NULL,
    kdf_t_cost INTEGER NOT NULL,
    kdf_parallelism INTEGER NOT NULL,
    master_wrap_nonce BYTEA NOT NULL,
    wrapped_dek_master BYTEA NOT NULL,
    recovery_wrap_nonce BYTEA,
    wrapped_dek_recovery BYTEA,
    payload_nonce BYTEA NOT NULL,
    payload_ciphertext BYTEA NOT NULL,
    envelope_checksum BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id)
);

CREATE INDEX IF NOT EXISTS idx_vault_envelopes_user_id ON vault_envelopes(user_id);

CREATE TABLE IF NOT EXISTS backup_index (
    backup_id TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vault_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    vault_revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    operation TEXT,
    envelope_sha256 TEXT NOT NULL,
    application_version TEXT,
    relative_path TEXT NOT NULL,
    bucket TEXT NOT NULL,
    valid INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_backup_index_user_id ON backup_index(user_id);

INSERT INTO app_meta(key, value)
VALUES ('schema_version', '2')
ON CONFLICT (key) DO UPDATE SET value = '2';
"""


async def init_schema(pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)


async def get_meta(pool, key: str) -> str | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM app_meta WHERE key = $1", key
        )
        return row["value"] if row else None


async def set_meta(pool, key: str, value: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO app_meta(key, value) VALUES($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            key, value,
        )
