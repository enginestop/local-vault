import io

from conftest import setup_vault


def _setup(client):
    token, _ = setup_vault(client)
    return {"Authorization": f"Bearer {token}"}


def test_import_commit(client):
    h = _setup(client)
    client.post("/api/v1/credentials", json={"name": "A", "username": "u", "password": "p"}, headers=h)
    before = client.get("/api/v1/credentials", headers=h).json()["total"]
    csv = "name,url,username,password,note\nImp,https://x.com,a@b.com,secret,n1\n"
    files = {"file": ("i.csv", csv, "text/csv")}
    r = client.post("/api/v1/imports/previews", files=files, data={"profile": "chromium"}, headers=h)
    assert r.status_code == 200
    pid = r.json()["id"]
    assert r.json()["valid_count"] == 1
    r = client.post(f"/api/v1/imports/previews/{pid}/commit", json={}, headers=h)
    assert r.status_code == 200
    assert r.json()["committed"] == 1
    after = client.get("/api/v1/credentials", headers=h).json()["total"]
    assert after == before + 1


def test_export_spreadsheet(client):
    h = _setup(client)
    client.post("/api/v1/credentials", json={"name": "A", "username": "u", "password": "p"}, headers=h)
    r = client.post(
        "/api/v1/exports",
        json={"master_password": "test123", "profile": "spreadsheet", "scope": "all"},
        headers=h,
    )
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    body = b"".join(r.iter_bytes()).decode("utf-8-sig")
    assert "name" in body.splitlines()[0]


def test_export_requires_master(client):
    h = _setup(client)
    client.post("/api/v1/credentials", json={"name": "A", "username": "u", "password": "p"}, headers=h)
    r = client.post(
        "/api/v1/exports",
        json={"master_password": "WRONG", "profile": "spreadsheet", "scope": "all"},
        headers=h,
    )
    assert r.status_code in (400, 401)


def test_backup_retention_and_restore(client):
    h = _setup(client)
    # create several mutations to generate backups
    for i in range(5):
        r = client.post("/api/v1/credentials", json={"name": f"C{i}", "password": "p"}, headers=h)
        assert r.status_code == 201
    r = client.get("/api/v1/backups", headers=h)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 5
    # restore the earliest backup
    earliest = min(items, key=lambda b: b["vault_revision"])
    r = client.post("/api/v1/backups/restore", data={"backup_id": earliest["backup_id"]}, headers=h)
    assert r.status_code == 200
