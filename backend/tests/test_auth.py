"""Tests for JWT auth: password hashing, token lifecycle, login routes, guard."""
from fastapi.testclient import TestClient

import app.main as main
from app.config import settings
from app.services import auth
from tests.conftest import FakeChat  # noqa: F401  (ensure env isolation)


class TestPasswordHashing:
    def test_roundtrip(self):
        hashed = auth.hash_password("secret123")
        assert hashed != "secret123"
        assert auth.verify_password("secret123", hashed) is True

    def test_wrong_password_rejected(self):
        hashed = auth.hash_password("secret123")
        assert auth.verify_password("wrong", hashed) is False

    def test_bad_format_rejected(self):
        assert auth.verify_password("x", "not-a-hash") is False


class TestTokenLifecycle:
    def _enable_jwt(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
        monkeypatch.setattr(settings, "ADMIN_PASSWORD", "adminpass")
        monkeypatch.setattr(settings, "ADMIN_DISPLAY_NAME", "Test Admin")
        monkeypatch.setattr(settings, "API_KEYS_RAW", "")

    def test_login_issues_token(self, monkeypatch):
        self._enable_jwt(monkeypatch)
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/login", json={"username": "admin", "password": "adminpass"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["username"] == "admin"
        assert body["user"]["role"] == "admin"
        payload = auth.decode_token(body["access_token"])
        assert payload["sub"] == "admin"

    def test_login_wrong_password(self, monkeypatch):
        self._enable_jwt(monkeypatch)
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/login", json={"username": "admin", "password": "nope"}
        )
        assert resp.status_code == 401

    def test_login_disabled_without_secret(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "")
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/login", json={"username": "a", "password": "b"}
        )
        assert resp.status_code == 403

    def test_me_requires_token(self, monkeypatch):
        self._enable_jwt(monkeypatch)
        client = TestClient(main.app)
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_valid_token(self, monkeypatch):
        self._enable_jwt(monkeypatch)
        client = TestClient(main.app)
        token = auth.create_access_token("admin")
        resp = client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["username"] == "admin"

    def test_me_with_tainted_token(self, monkeypatch):
        self._enable_jwt(monkeypatch)
        client = TestClient(main.app)
        resp = client.get(
            "/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"}
        )
        assert resp.status_code == 401

    def test_auth_status_reports_methods(self, monkeypatch):
        self._enable_jwt(monkeypatch)
        client = TestClient(main.app)
        data = client.get("/api/auth/status").json()
        assert data["auth_enabled"] is True
        assert data["login_enabled"] is True
        assert data["methods"] == {"jwt": True, "api_key": False}


class TestRegister:
    def _fake_register(self, monkeypatch, user=None, error=None):
        def fake(username, password, name=""):
            if error:
                raise error
            return user or {
                "username": username,
                "name": name or username,
                "role": "user",
            }

        monkeypatch.setattr(main, "register_user", fake)

    def test_signup_issues_token(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        monkeypatch.setattr(settings, "API_KEYS_RAW", "")
        self._fake_register(monkeypatch)
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/register",
            json={"username": "carol", "password": "longpassword1", "name": "Carol"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["user"]["username"] == "carol"
        assert body["user"]["role"] == "user"
        payload = auth.decode_token(body["access_token"])
        assert payload["sub"] == "carol"

    def test_signup_disabled_by_flag(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        monkeypatch.setattr(settings, "ALLOW_SIGNUP", False)
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/register",
            json={"username": "carol", "password": "longpassword1"},
        )
        assert resp.status_code == 403

    def test_signup_disabled_without_jwt(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "")
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/register",
            json={"username": "carol", "password": "longpassword1"},
        )
        assert resp.status_code == 403

    def test_duplicate_username_returns_400(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        self._fake_register(
            monkeypatch, error=ValueError("User 'carol' already exists")
        )
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/register",
            json={"username": "carol", "password": "longpassword1"},
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"]

    def test_short_password_rejected_by_model(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        client = TestClient(main.app)
        resp = client.post(
            "/api/auth/register",
            json={"username": "carol", "password": "short"},
        )
        assert resp.status_code == 422


class TestAskWithJwt:
    def test_ask_requires_jwt(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
        monkeypatch.setattr(settings, "ADMIN_PASSWORD", "adminpass")
        monkeypatch.setattr(settings, "API_KEYS_RAW", "")
        monkeypatch.setattr(
            main, "ask", lambda question, session_id=None: {"answer": "a", "sources": [], "session_id": session_id or "default"}
        )
        client = TestClient(main.app)
        assert client.post("/api/ask", json={"question": "hi"}).status_code == 401

    def test_ask_with_jwt_token(self, monkeypatch):
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        monkeypatch.setattr(settings, "ADMIN_USERNAME", "admin")
        monkeypatch.setattr(settings, "ADMIN_PASSWORD", "adminpass")
        monkeypatch.setattr(settings, "API_KEYS_RAW", "")
        monkeypatch.setattr(
            main, "ask", lambda question, session_id=None: {"answer": "a", "sources": [], "session_id": session_id or "default"}
        )
        client = TestClient(main.app)
        token = auth.create_access_token("admin")
        resp = client.post(
            "/api/ask",
            json={"question": "fees"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["answer"] == "a"

    def test_api_key_still_accepted(self, monkeypatch):
        # Backwards compatibility: legacy X-API-Key auth still works alongside JWT.
        monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret")
        monkeypatch.setattr(settings, "API_KEYS_RAW", "legacy-key")
        monkeypatch.setattr(
            main,
            "ask",
            lambda question, session_id=None: {
                "answer": "a",
                "sources": [],
                "session_id": session_id or "default",
            },
        )
        client = TestClient(main.app)
        assert client.post(
            "/api/ask",
            json={"question": "x"},
            headers={"X-API-Key": "legacy-key"},
        ).status_code == 200
        # Missing/unknown keys are still rejected.
        assert client.post("/api/ask", json={"question": "x"}).status_code == 401