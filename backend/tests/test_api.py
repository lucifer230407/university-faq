"""Route-level tests using FastAPI TestClient (business logic mocked)."""
from fastapi.testclient import TestClient

import app.main as main


def test_health_unhealthy_on_db_failure(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(main, "test_connection", boom)
    client = TestClient(main.app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "unhealthy"


def test_auth_status_reflects_config(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "k1")
    client = TestClient(main.app)
    assert client.get("/api/auth/status").json()["auth_enabled"] is True


def test_ask_requires_api_key(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "secret123")
    client = TestClient(main.app)
    resp = client.post("/api/ask", json={"question": "hello"})
    assert resp.status_code == 401


def test_ask_with_valid_key(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "secret123")
    monkeypatch.setattr(
        main,
        "ask",
        lambda question, session_id=None: {
            "answer": "answer",
            "sources": [
                {"text": "src", "metadata": {"agent_ns": "general"}, "score": 0.9}
            ],
            "session_id": session_id or "default",
        },
    )
    client = TestClient(main.app)
    resp = client.post(
        "/api/ask",
        json={"question": "fees"},
        headers={"X-API-Key": "secret123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "answer"
    assert body["sources"][0]["metadata"]["agent_ns"] == "general"


def test_ask_rejects_blank_question(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")
    client = TestClient(main.app)
    resp = client.post("/api/ask", json={"question": "   "})
    assert resp.status_code == 400  # handler rejects whitespace-only questions


def test_upload_rejects_empty_file(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "adminpass")
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")
    client = TestClient(main.app)
    token = main.create_access_token("admin")
    resp = client.post(
        "/api/documents",
        files={"file": ("x.txt", b"", "text/plain")},
        data={"agent_ns": "ns"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_upload_rejects_non_admin(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")

    def student(username):
        return {"username": username, "name": username, "role": "user"}

    monkeypatch.setattr("app.services.auth.get_user", student)
    client = TestClient(main.app)
    token = main.create_access_token("student")
    resp = client.post(
        "/api/documents",
        files={"file": ("x.txt", b"false claim", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_clear_accepts_session_id_only(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")
    client = TestClient(main.app)
    resp = client.post("/api/clear", json={"session_id": "abc"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "cleared", "session_id": "abc"}


def test_clear_accepts_empty_body(monkeypatch):
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")
    client = TestClient(main.app)
    resp = client.post("/api/clear", json={})
    assert resp.status_code == 200
    assert resp.json() == {"status": "cleared", "session_id": "default"}


def test_clear_rejects_question_field(monkeypatch):
    # Regression: the frontend "new chat" sends {"question":"",...}; the clear
    # endpoint must not validate the unrelated question field.
    settings = main.settings
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")
    client = TestClient(main.app)
    resp = client.post("/api/clear", json={"question": "", "session_id": "abc"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "cleared", "session_id": "abc"}