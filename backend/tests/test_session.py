from uuid import uuid4

from conftest import setup_vault


def test_setup_creates_recovery_key(client):
    token, rec = setup_vault(client)
    assert token
    assert rec and rec.startswith("LV1")


def test_setup_rejects_second_vault(client):
    setup_vault(client)
    r = client.post(
        "/api/v1/setup",
        json={
            "master_password": "other1",
            "confirm_master_password": "other1",
            "create_recovery_key": False,
            "language": "id",
            "weak_password_acknowledged": True,
            "http_lan_risk_acknowledged": True,
        },
    )
    assert r.status_code in (400, 409)


def test_unlock_wrong_then_correct(client):
    token, _ = setup_vault(client)
    r = client.post("/api/v1/sessions/lock", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 204
    tab_id = str(uuid4())
    r = client.post("/api/v1/sessions/unlock", json={"master_password": "WRONG", "tab_instance_id": tab_id})
    assert r.status_code == 401
    r = client.post("/api/v1/sessions/unlock", json={"master_password": "test123", "tab_instance_id": tab_id})
    assert r.status_code == 200


def test_recover_rotates_master(client):
    token, rec = setup_vault(client)
    client.post("/api/v1/sessions/lock", headers={"Authorization": f"Bearer {token}"})
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
    assert r.json().get("token")
    assert r.json().get("recovery_key")
    assert r.json()["recovery_key"] != rec
    r = client.post("/api/v1/sessions/unlock", json={"master_password": "test123", "tab_instance_id": str(uuid4())})
    assert r.status_code == 401
    r = client.post("/api/v1/sessions/unlock", json={"master_password": "newpass9", "tab_instance_id": str(uuid4())})
    assert r.status_code == 200


def test_reset_vault(client):
    token, _ = setup_vault(client)
    r = client.post(
        "/api/v1/settings/security/reset-vault",
        json={
            "master_password": "test123",
            "confirm_recovery_phrase": "RESET LOCALVAULT",
            "new_master_password": "resetpw1",
            "confirm_new_master_password": "resetpw1",
            "weak_password_acknowledged": True,
            "create_recovery_key": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json().get("recovery_key")
    client.post("/api/v1/sessions/lock", headers={"Authorization": f"Bearer {token}"})
    r = client.post("/api/v1/sessions/unlock", json={"master_password": "resetpw1", "tab_instance_id": str(uuid4())})
    assert r.status_code == 200
