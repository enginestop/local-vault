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

ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'admin_user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES users(id);
DO $$ BEGIN
    ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('superadmin', 'admin_user'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE users ADD CONSTRAINT users_status_check CHECK (account_status IN ('pending', 'active', 'disabled'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS vaults (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('shared', 'personal')),
    owner_id UUID REFERENCES users(id) ON DELETE CASCADE,
    dek_ciphertext BYTEA,
    dek_nonce BYTEA,
    revision INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((kind = 'shared' AND owner_id IS NULL) OR (kind = 'personal' AND owner_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vaults_shared ON vaults(kind) WHERE kind = 'shared';
CREATE UNIQUE INDEX IF NOT EXISTS idx_vaults_personal_owner ON vaults(owner_id) WHERE kind = 'personal';

CREATE TABLE IF NOT EXISTS vault_members (
    vault_id UUID NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vault_id, user_id)
);

CREATE TABLE IF NOT EXISTS vault_key_wrappings (
    vault_id UUID NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kek_salt BYTEA NOT NULL,
    wrapped_dek BYTEA NOT NULL,
    wrap_nonce BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (vault_id, user_id)
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
VALUES ('schema_version', '3')
ON CONFLICT (key) DO UPDATE SET value = '3';
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
