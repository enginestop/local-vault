from conftest import credential_replacement, setup_vault


def test_credential_crud(auth_headers, client):
    h = auth_headers
    r = client.post(
        "/api/v1/credentials",
        json={"name": "GitHub", "url": "https://github.com", "username": "me@x.com", "password": "pw", "tags": ["dev"]},
        headers=h,
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    rev = r.json()["revision"]
    assert rev == 1

    r = client.get("/api/v1/credentials", headers=h)
    assert r.status_code == 200
    assert r.json()["total"] == 1

    r = client.get(f"/api/v1/credentials/{cid}", headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "GitHub"

    r = client.put(
        f"/api/v1/credentials/{cid}",
        json=credential_replacement(r.json(), name="GitHub2"),
        headers={**h, "If-Match": f'"{rev}"'},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "GitHub2"
    assert r.json()["revision"] == 2


def test_update_requires_if_match(auth_headers, client):
    h = auth_headers
    r = client.post("/api/v1/credentials", json={"name": "A", "password": "p"}, headers=h)
    cid = r.json()["id"]
    r = client.put(f"/api/v1/credentials/{cid}", json=credential_replacement(r.json(), name="B"), headers=h)
    assert r.status_code == 428  # precondition required


def test_concurrent_update_conflict(auth_headers, client):
    h = auth_headers
    r = client.post("/api/v1/credentials", json={"name": "A", "password": "p"}, headers=h)
    cid = r.json()["id"]
    rev = r.json()["revision"]
    # first update succeeds
    original = r.json()
    r1 = client.put(f"/api/v1/credentials/{cid}", json=credential_replacement(original, name="B"), headers={**h, "If-Match": f'"{rev}"'})
    assert r1.status_code == 200
    new_rev = r1.json()["revision"]
    assert new_rev == rev + 1
    # stale update with old rev must fail
    r2 = client.put(f"/api/v1/credentials/{cid}", json=credential_replacement(original, name="C"), headers={**h, "If-Match": f'"{rev}"'})
    assert r2.status_code == 409
    assert r2.json()["code"] == "EDIT_CONFLICT"


def test_trash_and_restore(auth_headers, client):
    h = auth_headers
    r = client.post("/api/v1/credentials", json={"name": "A", "password": "p"}, headers=h)
    cid = r.json()["id"]
    rev = r.json()["revision"]
    r = client.post(f"/api/v1/credentials/{cid}/trash", json={}, headers={**h, "If-Match": f'"{rev}"'})
    assert r.status_code == 200
    r = client.get("/api/v1/trash", headers=h)
    assert r.json()["total"] == 1
    rev2 = client.get(f"/api/v1/credentials/{cid}", headers=h).json()["revision"]
    r = client.post(f"/api/v1/credentials/{cid}/restore", json={}, headers={**h, "If-Match": f'"{rev2}"'})
    assert r.status_code == 200
    r = client.get("/api/v1/trash", headers=h)
    assert r.json()["total"] == 0


def test_trash_empty(auth_headers, client):
    h = auth_headers
    for n in ("A", "B"):
        r = client.post("/api/v1/credentials", json={"name": n, "password": "p"}, headers=h)
        cid = r.json()["id"]
        rev = r.json()["revision"]
        client.post(f"/api/v1/credentials/{cid}/trash", json={}, headers={**h, "If-Match": f'"{rev}"'})
    r = client.get("/api/v1/trash", headers=h)
    assert r.json()["total"] == 2
    r = client.post("/api/v1/trash/empty", json={"confirmation": True, "count_expected": 2}, headers=h)
    assert r.status_code == 200
    r = client.get("/api/v1/trash", headers=h)
    assert r.json()["total"] == 0


def test_bulk_favorite(auth_headers, client):
    h = auth_headers
    ids = []
    for n in ("A", "B"):
        r = client.post("/api/v1/credentials", json={"name": n, "password": "p"}, headers=h)
        ids.append({"id": r.json()["id"], "revision": r.json()["revision"]})
    r = client.post("/api/v1/credentials/bulk", json={"action": "set_favorite", "ids": ids}, headers=h)
    assert r.status_code == 200
    assert r.json()["count"] == 2
    r = client.get("/api/v1/credentials", headers=h)
    assert all(c["favorite"] for c in r.json()["items"])


def test_password_generator(auth_headers, client):
    h = auth_headers
    r = client.post("/api/v1/password-generator", json={"length": 32, "include_symbols": True}, headers=h)
    assert r.status_code == 200
    pw = r.json()["password"]
    assert len(pw) == 32
    # uniqueness
    r2 = client.post("/api/v1/password-generator", json={"length": 32}, headers=h)
    assert r2.json()["password"] != pw


def test_categories_and_tags(auth_headers, client):
    h = auth_headers
    r = client.post("/api/v1/categories", json={"name": "Work"}, headers=h)
    assert r.status_code == 201
    r = client.get("/api/v1/categories", headers=h)
    assert r.status_code == 200
    assert len(r.json()["items"]) >= 1
    r = client.post("/api/v1/credentials", json={"name": "A", "password": "p", "tags": ["alpha", "beta"]}, headers=h)
    cid = r.json()["id"]
    r = client.get("/api/v1/tags", headers=h)
    assert r.status_code == 200
    assert "alpha" in r.json()["items"]
