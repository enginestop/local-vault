import os
import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://default:lafbVK2ijS3v@ep-ancient-art-a405hexn-pooler.us-east-1.aws.neon.tech/projek_adip?sslmode=require&channel_binding=require",
    )


def database_schema() -> str | None:
    value = os.environ.get("DATABASE_SCHEMA", "").strip()
    if not value:
        return None
    if not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise ValueError("DATABASE_SCHEMA must be a simple identifier")
    return value


async def create_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = {}
    schema = database_schema()
    if schema:
        settings["search_path"] = schema
    _pool = await asyncpg.create_pool(
        database_url(),
        min_size=2,
        max_size=10,
        command_timeout=30,
        server_settings=settings,
    )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool not initialized")
    return _pool
