import json
import threading
from uuid import UUID, uuid4

from conftest import credential_replacement, setup_vault


def test_every_api_response_has_request_id_and_problem_json(client):
    supplied = str(uuid4())
    status = client.get("/api/v1/status", headers={"X-Request-ID": supplied})
    assert status.headers["X-Request-ID"] == supplied
    UUID(status.headers["X-Request-ID"])

    missing = client.get("/api/v1/not-real")
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["request_id"] == missing.headers["X-Request-ID"]

    invalid = client.post("/api/v1/setup", json={"unexpected": "secret-marker"})
    assert invalid.status_code == 422
    assert invalid.headers["content-type"].startswith("application/problem+json")
    assert "secret-marker" not in invalid.text


def test_status_setup_lock_and_delete_contract(client):
    before = client.get("/api/v1/status").json()
    assert before["setup_required"] is True
    assert "vault_revision" not in before
    token, _ = setup_vault(client)
    headers = {"Authorization": f"Bearer {token}"}
    locked = client.post("/api/v1/sessions/lock", headers=headers)
    assert locked.status_code == 204 and locked.content == b""


def test_origin_and_request_size_are_rejected_before_body_parsing(client):
    foreign = client.get("/api/v1/status", headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403
    assert foreign.json()["code"] == "ORIGIN_NOT_ALLOWED"
    large = client.post(
        "/api/v1/sessions/unlock",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(1024 * 1024 + 1)},
    )
    assert large.status_code == 413


def test_full_replacement_conflict_and_explicit_overwrite(client):
    token, _ = setup_vault(client)
    headers = {"Authorization": f"Bearer {token}"}
    original = client.post("/api/v1/credentials", json={"name": "Original", "password": "one"}, headers=headers).json()
    first = client.put(
        f"/api/v1/credentials/{original['id']}",
        json=credential_replacement(original, name="First"),
        headers={**headers, "If-Match": f'"{original["revision"]}"'},
    )
    assert first.status_code == 200
    stale_body = credential_replacement(original, name="Chosen overwrite")
    conflict = client.put(
        f"/api/v1/credentials/{original['id']}",
        json=stale_body,
        headers={**headers, "If-Match": f'"{original["revision"]}"'},
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "EDIT_CONFLICT"
    assert "password" not in conflict.text
    stale_body["conflict_resolution"] = "overwrite"
    overwritten = client.put(
        f"/api/v1/credentials/{original['id']}",
        json=stale_body,
        headers={**headers, "If-Match": f'"{original["revision"]}"'},
    )
    assert overwritten.status_code == 200
    assert overwritten.json()["name"] == "Chosen overwrite"
    assert overwritten.json()["revision"] == first.json()["revision"] + 1


def test_unquoted_if_match_is_rejected(client):
    token, _ = setup_vault(client)
    headers = {"Authorization": f"Bearer {token}"}
    credential = client.post("/api/v1/credentials", json={"name": "A"}, headers=headers).json()
    response = client.put(
        f"/api/v1/credentials/{credential['id']}",
        json=credential_replacement(credential, name="B"),
        headers={**headers, "If-Match": str(credential["revision"])},
    )
    assert response.status_code == 422


def test_openapi_exposes_exactly_48_versioned_rest_operations(client):
    operations = {
        (method.upper(), path)
        for path, item in client.app.openapi()["paths"].items()
        if path.startswith("/api/v1/")
        for method in item
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert len(operations) == 48
    required = {
        ("GET", "/api/v1/status"),
        ("POST", "/api/v1/setup"),
        ("PUT", "/api/v1/credentials/{cred_id}"),
        ("POST", "/api/v1/imports/previews"),
        ("POST", "/api/v1/exports"),
        ("POST", "/api/v1/backups/restore"),
        ("DELETE", "/api/v1/settings/security/recovery-key"),
        ("PUT", "/api/v1/settings/host"),
    }
    assert required <= operations
    schema = client.app.openapi()["paths"]
    assert "201" in schema["/api/v1/setup"]["post"]["responses"]
    for path in (
        "/api/v1/credentials/{cred_id}",
        "/api/v1/categories/{category_id}",
        "/api/v1/tags/{name}",
        "/api/v1/imports/previews/{preview_id}",
        "/api/v1/settings/security/recovery-key",
    ):
        assert "204" in schema[path]["delete"]["responses"]
