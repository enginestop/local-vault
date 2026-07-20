import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

SCHEMA_VERSION = 1


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_envelope (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            vault_id TEXT NOT NULL,
            schema_version INTEGER NOT NULL,
            vault_revision INTEGER NOT NULL,
            format_version INTEGER NOT NULL,
            kdf_algorithm TEXT NOT NULL,
            kdf_salt BLOB NOT NULL,
            kdf_m_cost_kib INTEGER NOT NULL,
            kdf_t_cost INTEGER NOT NULL,
            kdf_parallelism INTEGER NOT NULL,
            master_wrap_nonce BLOB NOT NULL,
            wrapped_dek_master BLOB NOT NULL,
            recovery_wrap_nonce BLOB,
            wrapped_dek_recovery BLOB,
            payload_nonce BLOB NOT NULL,
            payload_ciphertext BLOB NOT NULL,
            envelope_checksum BLOB NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_index (
            backup_id TEXT PRIMARY KEY,
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
        )
        """
    )
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


@contextmanager
def immediate_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE for mutations (SEC/PRD: total order, durability)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
