from uuid import uuid4

from conftest import credential_replacement, setup_vault


def test_status_shape(client):
    setup_vault(client)
    r = client.get("/api/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["setup_required"] is False
    assert "vault_revision" not in body
    assert "setup_completed" not in body
    assert "locked" not in body


def test_protected_route_rejects_fake_token(client):
    token, _ = setup_vault(client)
    # lock the real session
    client.post("/api/v1/sessions/lock", headers={"Authorization": f"Bearer {token}"})
    # a token that merely has the Bearer prefix but is not a real session must be rejected
    r = client.get("/api/v1/credentials", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
    # missing token entirely must be rejected
    r2 = client.get("/api/v1/credentials")
    assert r2.status_code == 401


def test_protected_route_rejects_after_lock(client):
    token, _ = setup_vault(client)
    # valid while unlocked
    r = client.get("/api/v1/credentials", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    # lock, then the same token must no longer grant access
    client.post("/api/v1/sessions/lock", headers={"Authorization": f"Bearer {token}"})
    r2 = client.get("/api/v1/credentials", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 401
    status = client.get("/api/v1/status").json()
    assert status["setup_required"] is False


def test_status_all_and_sorting(auth_headers, client):
    headers = auth_headers
    first = client.post("/api/v1/credentials", json={"name": "Zulu"}, headers=headers).json()
    second = client.post("/api/v1/credentials", json={"name": "Alpha"}, headers=headers).json()
    third = client.post("/api/v1/credentials", json={"name": "Beta"}, headers=headers).json()
    client.post(
        f"/api/v1/credentials/{first['id']}/trash",
        headers={**headers, "If-Match": f'"{first["revision"]}"'},
    )
    all_items = client.get("/api/v1/credentials?status=all&page_size=100", headers=headers).json()["items"]
    assert {item["id"] for item in all_items} == {first["id"], second["id"], third["id"]}
    active = client.get(
        "/api/v1/credentials?status=active&sort_field=name&sort_direction=asc",
        headers=headers,
    ).json()["items"]
    assert [item["name"] for item in active] == ["Alpha", "Beta"]


def test_unlock_purges_expired_trash(client):
    token, _ = setup_vault(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post("/api/v1/credentials", json={"name": "Expired"}, headers=headers).json()
    client.post(
        f"/api/v1/credentials/{created['id']}/trash",
        headers={**headers, "If-Match": f'"{created["revision"]}"'},
    )
    ctx = client.app.state.ctx
    target = next(c for c in ctx.vault.plaintext.credentials if c.id == created["id"])
    target.deleted_at = "2000-01-01T00:00:00.000Z"
    client.portal.call(ctx.vault.mutate, lambda payload: payload)
    client.post("/api/v1/sessions/lock", headers=headers)
    unlocked = client.post(
        "/api/v1/sessions/unlock",
        json={"master_password": "test123", "tab_instance_id": str(uuid4())},
    )
    assert unlocked.status_code == 200
    new_headers = {"Authorization": f"Bearer {unlocked.json()['token']}"}
    all_items = client.get("/api/v1/credentials?status=all", headers=new_headers).json()["items"]
    assert created["id"] not in {item["id"] for item in all_items}


def test_recover_invalidates_other_sessions(client):
    token, rec = setup_vault(client)
    # open a second session
    r2 = client.post("/api/v1/sessions/unlock", json={"master_password": "test123", "tab_instance_id": str(uuid4())})
    assert r2.status_code == 200
    token2 = r2.json()["token"]
    # recover (rotates master) -> invalidates all sessions
    r = client.post(
        "/api/v1/sessions/recover",
        json={
            "recovery_key": rec,
            "new_master_password": "newpass9",
            "confirm_new_master_password": "newpass9",
            "weak_password_acknowledged": True,
            "tab_instance_id": str(uuid4()),
        },
    )
    assert r.status_code == 200
    # the old session token must now be rejected
    r3 = client.get("/api/v1/credentials", headers={"Authorization": f"Bearer {token2}"})
    assert r3.status_code == 401


def test_import_preserves_password_and_notes(client):
    token, _ = setup_vault(client)
    csv_text = "name,url,username,password,notes\nGitHub,https://github.com,me,sup3rsecret,my note\n"
    files = {"file": ("imp.csv", csv_text.encode("utf-8-sig"), "text/csv")}
    r = client.post(
        "/api/v1/imports/previews",
        files=files,
        data={"profile": "generic"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    r = client.post(
        f"/api/v1/imports/previews/{pid}/commit",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["committed"] == 1
    creds = client.get("/api/v1/credentials", headers={"Authorization": f"Bearer {token}"}).json()["items"]
    gh = next((c for c in creds if c["name"] == "GitHub"), None)
    assert gh is not None
    assert gh["password"] == "sup3rsecret"
    assert gh["notes"] == "my note"


def test_generator_returns_strength(client):
    token, _ = setup_vault(client)
    r = client.post(
        "/api/v1/password-generator",
        json={"length": 20, "include_lowercase": True, "include_uppercase": True, "include_digits": True, "include_symbols": True, "exclude_ambiguous": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "password" in body and "strength" in body
    assert body["strength"] in ("weak", "good", "strong")


def test_password_update_records_history(client):
    token, _ = setup_vault(client)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/credentials",
        json={"name": "History test", "password": "old-password"},
        headers=headers,
    )
    assert created.status_code == 201
    credential = created.json()
    updated = client.put(
        f"/api/v1/credentials/{credential['id']}",
        json=credential_replacement(credential, password="new-password"),
        headers={**headers, "If-Match": f'"{credential["revision"]}"'},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["password"] == "new-password"
    assert body["password_history"][0]["password"] == "old-password"


def test_recovery_key_status_endpoint(client):
    token, _ = setup_vault(client)
    r = client.get("/api/v1/settings/security/recovery-key", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["recovery_key_present"] is True
