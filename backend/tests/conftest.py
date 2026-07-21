import os
import shutil
import asyncio
from uuid import uuid4

import pytest
import asyncpg

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def data_dir(tmp_path):
    d = os.path.join(str(tmp_path), "LocalVault-Data")
    os.makedirs(d, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


async def _create_schema(database_url: str, schema: str) -> None:
    conn = await asyncpg.connect(database_url, timeout=1)
    try:
        await conn.execute(f'CREATE SCHEMA "{schema}"')
    finally:
        await conn.close()


async def _drop_schema(database_url: str, schema: str) -> None:
    conn = await asyncpg.connect(database_url, timeout=1)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await conn.close()


async def _check_database(database_url: str) -> None:
    conn = await asyncpg.connect(database_url, timeout=1)
    await conn.close()


@pytest.fixture
def postgres_available():
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://localvault:localvault@localhost:5432/localvault",
    )
    try:
        asyncio.run(_check_database(database_url))
    except (OSError, asyncpg.PostgresError):
        return False
    return True


@pytest.fixture
def client(data_dir, monkeypatch, postgres_available):
    import sys

    if not postgres_available:
        pytest.skip("PostgreSQL is required for backend integration tests")
    sys.path.insert(0, BACKEND_ROOT)
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://localvault:localvault@localhost:5432/localvault",
    )
    schema = f"test_{uuid4().hex}"
    try:
        asyncio.run(_create_schema(database_url, schema))
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL is required for backend integration tests: {exc}")
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    from fastapi.testclient import TestClient
    from localvault.main import create_app

    app = create_app(data_dir)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as c:
            yield c
    finally:
        asyncio.run(_drop_schema(database_url, schema))


def setup_vault(client, master_password="test123", language="id"):
    body = {
        "master_password": master_password,
        "confirm_master_password": master_password,
        "create_recovery_key": True,
        "language": language,
        "weak_password_acknowledged": True,
        "http_lan_risk_acknowledged": True,
    }
    r = client.post("/api/v1/setup", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"], r.json().get("recovery_key")


def credential_replacement(credential, **changes):
    """Build the normative full-replacement PUT body from an API entity."""
    body = {
        key: credential[key]
        for key in (
            "name", "url", "username", "password", "category_id", "tags",
            "favorite", "notes", "custom_fields",
        )
    }
    body.update(changes)
    body["base_revision"] = credential["revision"]
    return body


@pytest.fixture
def auth_headers(client):
    token, _ = setup_vault(client)
    return {"Authorization": f"Bearer {token}"}
