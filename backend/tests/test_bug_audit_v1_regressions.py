import csv
import io
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from conftest import credential_replacement, setup_vault


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _preview(client, token, text, profile="generic"):
    response = client.post(
        "/api/v1/imports/previews",
        files={"file": ("import.csv", text.encode("utf-8"), "text/csv")},
        data={"profile": profile},
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_host_allowlist_and_spa_fallback_do_not_serve_arbitrary_files(client):
    assert client.get("/api/v1/status", headers={"Host": "127.0.0.1"}).status_code == 200
    assert client.get("/api/v1/status", headers={"Host": "evil.example"}).status_code == 400

    for path in ("/../main.py", "/%2e%2e/main.py", "/C:/Windows/win.ini"):
        response = client.get(path)
        assert response.status_code in (200, 404)
        assert b"def create_app" not in response.content
        assert b"[extensions]" not in response.content
    assert client.get("/api/v1/does-not-exist").status_code == 404


def test_backup_transactions_retention_and_unique_paths(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    manual = client.post("/api/v1/backups/manual", headers=headers)
    assert manual.status_code == 200, manual.text
    assert client.app.state.ctx.conn.in_transaction is False

    created = client.post(
        "/api/v1/credentials", json={"name": "Retention"}, headers=headers
    ).json()
    for index in range(12):
        response = client.put(
            f"/api/v1/credentials/{created['id']}",
            json=credential_replacement(created, notes=f"revision-{index}"),
            headers={**headers, "If-Match": f'"{created["revision"]}"'},
        )
        assert response.status_code == 200, response.text
        created = response.json()
        assert client.app.state.ctx.conn.in_transaction is False

    manifests = client.get("/api/v1/backups", headers=headers).json()["items"]
    valid_versions = [item for item in manifests if item["valid"] and item["bucket"] == "version"]
    assert len(valid_versions) <= 10
    assert len({item["relative_path"] for item in valid_versions}) == len(valid_versions)
    for item in valid_versions:
        path = os.path.join(client.app.state.ctx.backups.data_dir, item["relative_path"])
        assert os.path.isfile(path)


def test_invalid_update_is_rejected_and_vault_still_unlocks(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    created = client.post(
        "/api/v1/credentials", json={"name": "Still valid"}, headers=headers
    ).json()
    invalid = client.put(
        f"/api/v1/credentials/{created['id']}",
        json=credential_replacement(created, name="   "),
        headers={**headers, "If-Match": f'"{created["revision"]}"'},
    )
    assert invalid.status_code == 422
    assert client.app.state.ctx.conn.in_transaction is False

    client.post("/api/v1/sessions/lock-all", headers=headers)
    unlocked = client.post(
        "/api/v1/sessions/unlock",
        json={"master_password": "test123", "tab_instance_id": str(uuid4())},
    )
    assert unlocked.status_code == 200
    item = client.get(
        f"/api/v1/credentials/{created['id']}", headers=_headers(unlocked.json()["token"])
    ).json()
    assert item["name"] == "Still valid"


def test_shared_master_password_policy(client):
    empty_setup = client.post(
        "/api/v1/setup",
        json={
            "master_password": "   ",
            "confirm_master_password": "   ",
            "create_recovery_key": False,
            "language": "id",
            "weak_password_acknowledged": True,
            "http_lan_risk_acknowledged": True,
        },
    )
    assert empty_setup.status_code == 422

    token, recovery_key = setup_vault(client)
    weak_change = client.put(
        "/api/v1/settings/security/master-password",
        json={
            "current_master_password": "test123",
            "new_master_password": "short",
            "confirm_new_master_password": "short",
            "weak_password_acknowledged": False,
        },
        headers=_headers(token),
    )
    assert weak_change.status_code == 422
    client.post("/api/v1/sessions/lock-all", headers=_headers(token))
    empty_recovery = client.post(
        "/api/v1/sessions/recover",
        json={
            "recovery_key": recovery_key,
            "new_master_password": "",
            "confirm_new_master_password": "",
            "weak_password_acknowledged": True,
            "tab_instance_id": str(uuid4()),
        },
    )
    assert empty_recovery.status_code == 422


def test_import_previews_are_repeatable_and_session_owned(client):
    token, _ = setup_vault(client)
    second = client.post(
        "/api/v1/sessions/unlock",
        json={"master_password": "test123", "tab_instance_id": str(uuid4())},
    ).json()["token"]
    csv_text = "name,url,username,password\nOne,https://one.test,user,secret\n"
    first = _preview(client, token, csv_text)
    second_preview = _preview(client, token, csv_text)
    assert first["id"] != second_preview["id"]

    for method in ("get", "put", "post", "delete"):
        url = f"/api/v1/imports/previews/{first['id']}"
        if method == "post":
            url += "/commit"
        if method in ("put", "post"):
            response = getattr(client, method)(url, json={}, headers=_headers(second))
        else:
            response = getattr(client, method)(url, headers=_headers(second))
        assert response.status_code == 403, (method, response.text)


def test_import_update_conflict_with_category_and_password_history(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    original = client.post(
        "/api/v1/credentials",
        json={
            "name": "Original",
            "url": "https://same.test/login",
            "username": "user",
            "password": "old-secret",
        },
        headers=headers,
    ).json()
    preview = _preview(
        client,
        token,
        "name,url,username,password,category\nUpdated,https://same.test/login,user,new-secret,Imported\n",
    )
    assert preview["conflict_count"] == 1
    updated = client.put(
        f"/api/v1/imports/previews/{preview['id']}",
        json={"resolutions": [{"row_number": 1, "resolution": "update"}]},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    committed = client.post(
        f"/api/v1/imports/previews/{preview['id']}/commit", headers=headers
    )
    assert committed.status_code == 200, committed.text
    result = client.get(f"/api/v1/credentials/{original['id']}", headers=headers).json()
    assert result["name"] == "Updated"
    assert result["password"] == "new-secret"
    assert result["password_history"][0]["password"] == "old-secret"
    categories = client.get("/api/v1/categories", headers=headers).json()["items"]
    assert next(item for item in categories if item["name"] == "Imported")["id"] == result["category_id"]


def test_generator_preserves_every_selected_character_class(client):
    token, _ = setup_vault(client)
    response = client.post(
        "/api/v1/password-generator",
        json={
            "length": 64,
            "include_lowercase": True,
            "include_uppercase": True,
            "include_digits": True,
            "include_symbols": True,
            "exclude_ambiguous": True,
        },
        headers=_headers(token),
    )
    assert response.status_code == 200, response.text
    password = response.json()["password"]
    assert any(character.islower() for character in password)
    assert any(character.isupper() for character in password)
    assert any(character.isdigit() for character in password)
    assert any(not character.isalnum() for character in password)
    assert not set(password).intersection(set("Il1O0o|\\`'\""))


def test_filtered_export_matches_active_filters(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    matching = client.post(
        "/api/v1/credentials",
        json={"name": "Wanted", "tags": ["red", "blue"], "favorite": True},
        headers=headers,
    ).json()
    hidden = client.post(
        "/api/v1/credentials",
        json={"name": "Hidden", "tags": ["red", "blue"], "favorite": True},
        headers=headers,
    ).json()
    client.post(
        f"/api/v1/credentials/{hidden['id']}/trash",
        headers={**headers, "If-Match": f'"{hidden["revision"]}"'},
    )
    response = client.post(
        "/api/v1/exports",
        json={
            "master_password": "test123",
            "profile": "spreadsheet",
            "scope": "filtered",
            "filter": {
                "q": "Wanted",
                "tags": ["red", "blue"],
                "favorite_only": True,
                "status": "active",
                "tag_mode": "and",
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [row["name"] for row in rows] == [matching["name"]]
    assert "filename=" in response.headers["content-disposition"]


def test_stale_bulk_and_tag_revisions_are_rejected(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    credential = client.post(
        "/api/v1/credentials", json={"name": "Revision"}, headers=headers
    ).json()
    stale = client.post(
        "/api/v1/credentials/bulk",
        json={
            "action": "set_favorite",
            "ids": [{"id": credential["id"], "revision": credential["revision"] + 1}],
            "arguments": {},
        },
        headers=headers,
    )
    assert stale.status_code == 409
    invalid = client.post(
        "/api/v1/credentials/bulk",
        json={"action": "unknown", "ids": [], "arguments": {}},
        headers=headers,
    )
    assert invalid.status_code == 422

    tag = client.post("/api/v1/tags", json={"name": "before"}, headers=headers)
    assert tag.status_code in (200, 201)
    revision = client.get("/api/v1/tags", headers=headers).json()["vault_revision"]
    assigned = client.put(
        f"/api/v1/credentials/{credential['id']}",
        json=credential_replacement(credential, tags=["before"]),
        headers={**headers, "If-Match": f'"{credential["revision"]}"'},
    ).json()
    revision = client.get("/api/v1/tags", headers=headers).json()["vault_revision"]
    renamed = client.post(
        "/api/v1/tags/rename",
        json={"source": "before", "target": "after"},
        headers={**headers, "X-Vault-Revision": str(revision)},
    )
    assert renamed.status_code == 200, renamed.text
    refreshed = client.get(f"/api/v1/credentials/{credential['id']}", headers=headers).json()
    assert refreshed["revision"] == assigned["revision"] + 1
    stale_tag = client.delete(
        "/api/v1/tags/after",
        headers={**headers, "X-Vault-Revision": str(revision)},
    )
    assert stale_tag.status_code == 409


def test_backup_parser_rejects_trailing_bytes(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    backup = client.post("/api/v1/backups/manual", headers=headers).json()
    downloaded = client.get(
        f"/api/v1/backups/{backup['backup_id']}/download", headers=headers
    )
    assert downloaded.status_code == 200
    corrupt = client.post(
        "/api/v1/backups/restore",
        files={"file": ("corrupt.lvbak", downloaded.content + b"trailing", "application/octet-stream")},
        headers=headers,
    )
    assert corrupt.status_code == 422


def test_valid_restore_replaces_payload_and_invalidates_sessions(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    credential = client.post(
        "/api/v1/credentials",
        json={"name": "Restore me", "notes": "before"},
        headers=headers,
    ).json()
    backup = client.post("/api/v1/backups/manual", headers=headers).json()
    changed = client.put(
        f"/api/v1/credentials/{credential['id']}",
        json=credential_replacement(credential, notes="after"),
        headers={**headers, "If-Match": f'"{credential["revision"]}"'},
    )
    assert changed.status_code == 200
    restored = client.post(
        "/api/v1/backups/restore",
        data={"backup_id": backup["backup_id"]},
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert client.get("/api/v1/credentials", headers=headers).status_code == 401
    unlocked = client.post(
        "/api/v1/sessions/unlock",
        json={"master_password": "test123", "tab_instance_id": str(uuid4())},
    )
    item = client.get(
        f"/api/v1/credentials/{credential['id']}",
        headers=_headers(unlocked.json()["token"]),
    ).json()
    assert item["notes"] == "before"


def test_localvault_export_import_round_trip(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    created = client.post(
        "/api/v1/credentials",
        json={
            "name": "=Formula",
            "password": "round-trip",
            "notes": "@not-a-formula",
            "custom_fields": [
                {"label": "Secret answer", "type": "secret", "value": "+value"}
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    exported = client.post(
        "/api/v1/exports",
        json={"master_password": "test123", "profile": "spreadsheet", "scope": "all"},
        headers=headers,
    )
    preview = _preview(client, token, exported.content.decode("utf-8-sig"), "auto")
    assert preview["profile"] == "localvault"
    committed = client.post(
        f"/api/v1/imports/previews/{preview['id']}/commit", headers=headers
    )
    assert committed.status_code == 200, committed.text
    credentials = client.get(
        "/api/v1/credentials?status=all&page_size=100", headers=headers
    ).json()["items"]
    imported = [item for item in credentials if item["name"] == "=Formula"]
    assert len(imported) == 2
    assert imported[-1]["notes"] == "@not-a-formula"
    assert imported[-1]["custom_fields"][0]["value"] == "+value"


def test_websocket_receives_entity_specific_event(client):
    token, _ = setup_vault(client)
    headers = _headers(token)
    ticket = client.post("/api/v1/sessions/event-ticket", headers=headers).json()["ticket"]
    with client.websocket_connect(
        f"/api/v1/events?ticket={ticket}", headers={"Host": "127.0.0.1"}
    ) as websocket:
        websocket.send_json({"type": "sync_state", "last_seen_vault_revision": 1})
        created = client.post(
            "/api/v1/credentials", json={"name": "Event target"}, headers=headers
        )
        assert created.status_code == 201
        event = websocket.receive_json()
        assert event["type"] == "credential.created"
        assert event["entity_type"] == "credential"
        assert event["entity_id"] == created.json()["id"]
        assert event["entity_revision"] == 1
        assert event["vault_revision"] >= 2


def test_session_has_no_idle_or_absolute_expiry_but_disconnect_grace_expires():
    from localvault.services.session_manager import SessionManager

    manager = SessionManager()
    session = manager.create_session("secret-token", str(uuid4()), "test")
    session.last_active_at = datetime.now(timezone.utc) - timedelta(days=1)
    assert manager.cleanup_expired() == 0
    assert manager.get_by_token("secret-token") is session
    session.disconnect_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert manager.cleanup_expired() == 1
    assert manager.get_by_token("secret-token") is None
