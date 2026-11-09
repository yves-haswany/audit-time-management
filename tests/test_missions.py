def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return r.json()["token"]


def test_lena_sees_her_missions(client):
    tok = _login(client, "LEE", "lee")
    r = client.get("/api/me/missions", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    ms = r.json()
    assert len(ms) >= 1
    assert any(m["CustomerName"] == "Saradar Bank" for m in ms)


def test_employee_without_work_gets_empty(client):
    tok = _login(client, "AGN", "agn")
    r = client.get("/api/me/missions", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    assert r.json() == []


def test_summary_reports_has_work_false(client):
    tok = _login(client, "AGN", "agn")
    r = client.get("/api/me/summary", headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 200
    assert r.json()["HasWork"] is False