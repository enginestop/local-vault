import os
import shutil

import pytest

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def data_dir(tmp_path):
    d = os.path.join(str(tmp_path), "LocalVault-Data")
    os.makedirs(d, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def client(data_dir):
    import sys

    sys.path.insert(0, BACKEND_ROOT)
    from fastapi.testclient import TestClient
    from localvault.main import create_app

    app = create_app(data_dir)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


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
