def test_login_success(client):
    r = client.post("/api/auth/login", json={"username": "LEE", "password": "lee"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    assert body["employee"]["EmployeeName"] == "Lena Elias El Feghaly"


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", json={"username": "LEE", "password": "nope"})
    assert r.status_code == 401


def test_logout_requires_token(client):
    r = client.post("/api/auth/logout")
    assert r.status_code == 401