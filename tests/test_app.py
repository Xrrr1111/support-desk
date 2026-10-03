from fastapi.testclient import TestClient

from backend import app as support


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(support, "DATABASE", tmp_path / "support.sqlite3")
    monkeypatch.setattr(support, "STAFF_TOKEN", "staff-secret")
    monkeypatch.setattr(support, "GATEWAY_URL", "")
    support.init_database()
    return TestClient(support.app), {"Authorization": "Bearer staff-secret"}


def test_verified_answer_and_handoff(tmp_path, monkeypatch):
    client, headers = setup(tmp_path, monkeypatch)
    assert client.post("/api/orders", json={"order_id": "ORD-100", "status": "shipped", "note": "sent yesterday"}).status_code == 401
    assert client.post("/api/orders", headers=headers, json={"order_id": "ORD-100", "status": "shipped", "note": "sent yesterday"}).status_code == 201
    assert client.post("/api/policies", headers=headers, json={"title": "Shipping delay", "body": "When shipping is delayed, contact customer support after three days."}).status_code == 201
    answered = client.post("/api/ask", headers=headers, json={"order_id": "ORD-100", "question": "Is there a shipping delay?"})
    assert answered.status_code == 200
    assert answered.json()["mode"] == "verified-template"
    assert answered.json()["sources"][0]["title"] == "Shipping delay"
    missing = client.post("/api/ask", headers=headers, json={"order_id": "ORD-999", "question": "Where is the package?"})
    assert missing.json()["mode"] == "handoff"
    ticket_id = missing.json()["ticket_id"]
    assert client.patch(f"/api/tickets/{ticket_id}", headers=headers, json={"status": "resolved", "resolution": "Called customer"}).status_code == 200
    assert client.get("/api/tickets", headers=headers).json()["tickets"][0]["status"] == "resolved"


def test_no_policy_means_no_fabricated_answer(tmp_path, monkeypatch):
    client, headers = setup(tmp_path, monkeypatch)
    client.post("/api/orders", headers=headers, json={"order_id": "ORD-200", "status": "processing"})
    response = client.post("/api/ask", headers=headers, json={"order_id": "ORD-200", "question": "Can I get a refund?"})
    assert response.json()["mode"] == "handoff"
    assert response.json()["sources"] == []


def test_unrelated_policy_creates_handoff(tmp_path, monkeypatch):
    client, headers = setup(tmp_path, monkeypatch)
    client.post("/api/orders", headers=headers, json={"order_id": "ORD-300", "status": "processing"})
    client.post("/api/policies", headers=headers, json={"title": "Shipping delay", "body": "Contact support after a three day shipping delay."})
    response = client.post("/api/ask", headers=headers, json={"order_id": "ORD-300", "question": "Can I get an invoice?"})
    assert response.json()["mode"] == "handoff"
