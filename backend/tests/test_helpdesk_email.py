"""Tests for the help-desk email fallback (draft + SMTP + RAG integration).

SMTP transport is faked; no real network or credentials are involved.
"""
import email
import smtplib

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.services import chat, helpdesk_email
from tests.conftest import FakeChat


@pytest.fixture(autouse=True)
def disable_web(monkeypatch):
    # Never hit the web during these tests.
    monkeypatch.setattr(settings, "WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "none")
    yield


@pytest.fixture
def smtp_config(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test.local")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(settings, "SMTP_USERNAME", "bot@test.local")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "s3cret")
    monkeypatch.setattr(settings, "HELPDESK_EMAIL", "helpdesk@example.com")
    monkeypatch.setattr(settings, "EMAIL_SEND_TIMEOUT", 5)
    monkeypatch.setattr(settings, "EMAIL_SIGNATURE_NAME", "University FAQ Assistant User")
    return settings


@pytest.fixture
def disable_auth(monkeypatch):
    monkeypatch.setattr(settings, "API_KEYS_RAW", "")
    monkeypatch.setattr(settings, "JWT_SECRET", "")


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls_called = False
        self.login_called = False
        self.sent = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        return None

    def starttls(self):
        self.tls_called = True

    def login(self, username, password):
        self.login_called = True

    def send_message(self, message):
        self.sent.append(message)


class BoomSMTP(FakeSMTP):
    def starttls(self):
        raise smtplib.SMTPException("535 5.7.8 authentication failed")


def last_sent_message():
    return FakeSMTP.instances[-1].sent[-1]


# --------------------------------------------------------------------------
# Draft generation
# --------------------------------------------------------------------------

class TestDraftGeneration:
    def test_thursday_menu_subject_and_body(self, smtp_config):
        draft = helpdesk_email.generate_email_draft(
            "What is the dinner menu for Thursday?"
        )
        assert draft["to"] == "helpdesk@example.com"
        assert draft["subject"] == "Request for Thursday Dinner Menu"
        assert "I would like to know the dinner menu for Thursday." in draft["body"]
        assert "Could you please provide the current dinner menu?" in draft["body"]
        assert "University FAQ Assistant User" in draft["body"]

    def test_generic_question(self, smtp_config):
        draft = helpdesk_email.generate_email_draft(
            "When is the last date to apply for re-evaluation?"
        )
        assert "re-evaluation" in draft["subject"].lower()
        assert "last date to apply for re-evaluation" in draft["body"]

    def test_no_hardcoding_by_content(self, smtp_config):
        draft = helpdesk_email.generate_email_draft(
            "What is the hostel WiFi password?"
        )
        assert "wifi password" in draft["body"].lower()
        assert draft["subject"] != "Request for Thursday Dinner Menu"

    def test_empty_question_rejected(self, smtp_config):
        with pytest.raises(ValueError):
            helpdesk_email.generate_email_draft("   \n  ")

    def test_header_injection_sanitized(self, smtp_config):
        draft = helpdesk_email.generate_email_draft(
            "What is the wifi password?\r\nBcc: evil@attacker.example\nSubject: hacked"
        )
        # Control chars are stripped, so no new lines can smuggle headers.
        assert "\r" not in draft["subject"]
        assert "\n" not in draft["subject"]
        assert "\r" not in draft["body"]
        # Build the real MIME header block and prove nothing was injected.
        raw = f"To: helpdesk@example.com\nSubject: {draft['subject']}\n\n{draft['body']}"
        msg = email.message_from_string(raw)
        assert msg.get_all("Subject") == [draft["subject"]]
        assert msg.get_all("Bcc") is None
        assert msg.get_all("Cc") is None

    def test_signature_configurable(self, smtp_config):
        settings.EMAIL_SIGNATURE_NAME = "Chitkara Helpdesk Bot"
        draft = helpdesk_email.generate_email_draft("How do I get a transcript?")
        assert draft["body"].endswith("Chitkara Helpdesk Bot")


# --------------------------------------------------------------------------
# SMTP sending
# --------------------------------------------------------------------------

class TestSmtpSend:
    def test_email_configured_when_set(self, smtp_config):
        assert helpdesk_email.email_configured() is True

    def test_email_not_configured_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "SMTP_HOST", None)
        monkeypatch.setattr(settings, "SMTP_PORT", 0)
        monkeypatch.setattr(settings, "SMTP_USERNAME", None)
        monkeypatch.setattr(settings, "SMTP_PASSWORD", None)
        monkeypatch.setattr(settings, "HELPDESK_EMAIL", None)
        assert helpdesk_email.email_configured() is False

    def test_send_success(self, smtp_config, monkeypatch):
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", FakeSMTP)
        result = helpdesk_email.send_email(
            subject="Request for Thursday Dinner Menu", body="Dear Help Desk,"
        )
        assert result["success"] is True
        assert "sent successfully" in result["message"]
        message = last_sent_message()
        assert message["To"] == "helpdesk@example.com"
        assert message["Subject"] == "Request for Thursday Dinner Menu"
        assert message["From"] == "bot@test.local"

    def test_send_always_uses_configured_recipient(self, smtp_config, monkeypatch):
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", FakeSMTP)
        helpdesk_email.send_email(
            to="attacker@example.com",
            subject="Request",
            body="How do I reset my portal password?",
        )
        assert last_sent_message()["To"] == "helpdesk@example.com"

    def test_send_turns_tls_on(self, smtp_config, monkeypatch):
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", FakeSMTP)
        helpdesk_email.send_email(subject="S", body="B")
        instance = FakeSMTP.instances[-1]
        assert instance.tls_called is True
        assert instance.login_called is True
        assert len(instance.sent) == 1

    def test_send_implicit_tls_uses_ssl(self, smtp_config, monkeypatch):
        monkeypatch.setattr(settings, "SMTP_USE_TLS", False)
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", FakeSMTP)
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP_SSL", FakeSMTP)
        helpdesk_email.send_email(subject="S", body="B")
        instance = FakeSMTP.instances[-1]
        assert instance.tls_called is False
        assert instance.login_called is True
        assert len(instance.sent) == 1

    def test_send_failure_raises_clean_error(self, smtp_config, monkeypatch):
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", BoomSMTP)
        with pytest.raises(helpdesk_email.HelpDeskEmailError) as exc_info:
            helpdesk_email.send_email(subject="S", body="B")
        # No credentials or stack traces leak to the caller.
        assert "s3cret" not in exc_info.value.args[0]


# --------------------------------------------------------------------------
# API endpoints
# --------------------------------------------------------------------------

class TestEmailEndpoints:
    def test_draft_requires_auth(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEYS_RAW", "secret123")
        client = TestClient(app)
        resp = client.post(
            "/api/email/draft", json={"question": "What is the dinner menu?"}
        )
        assert resp.status_code == 401

    def test_draft_service_not_configured(self, disable_auth):
        client = TestClient(app)
        resp = client.post(
            "/api/email/draft", json={"question": "What is the dinner menu?"}
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    def test_draft_success(self, smtp_config, disable_auth):
        client = TestClient(app)
        resp = client.post(
            "/api/email/draft",
            json={"question": "What is the dinner menu for Thursday?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["email"]["subject"] == "Request for Thursday Dinner Menu"
        assert body["email"]["to"] == "helpdesk@example.com"

    def test_draft_empty_question(self, smtp_config, disable_auth):
        client = TestClient(app)
        resp = client.post("/api/email/draft", json={"question": "   "})
        assert resp.status_code == 400

    def test_send_requires_auth(self, smtp_config, monkeypatch):
        monkeypatch.setattr(settings, "API_KEYS_RAW", "secret123")
        client = TestClient(app)
        resp = client.post(
            "/api/email/send",
            json={"subject": "Hi", "body": "Hello help desk"},
        )
        assert resp.status_code == 401

    def test_send_success(self, smtp_config, disable_auth, monkeypatch):
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", FakeSMTP)
        client = TestClient(app)
        resp = client.post(
            "/api/email/send",
            json={
                "to": "attacker@example.com",
                "subject": "Request for Dinner Menu",
                "body": "Dear Help Desk,",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        # Arbitrary client-supplied destination is ignored.
        assert last_sent_message()["To"] == "helpdesk@example.com"

    def test_send_failure_clean_message(self, smtp_config, disable_auth, monkeypatch):
        monkeypatch.setattr(helpdesk_email.smtplib, "SMTP", BoomSMTP)
        client = TestClient(app)
        resp = client.post(
            "/api/email/send",
            json={"subject": "Hi", "body": "Hello help desk"},
        )
        assert resp.status_code == 502
        detail = resp.json()["detail"]
        assert "s3cret" not in detail
        assert "try again later" in detail

    def test_send_missing_fields(self, smtp_config, disable_auth):
        client = TestClient(app)
        resp = client.post("/api/email/send", json={"subject": "", "body": ""})
        assert resp.status_code == 400


# --------------------------------------------------------------------------
# /api/ask RAG integration
# --------------------------------------------------------------------------

def fake_doc(text, ns, score):
    return {"text": text, "metadata": {"agent_ns": ns}, "score": score}


@pytest.fixture
def clear_history(monkeypatch):
    chat.conversations.clear("test-email")
    monkeypatch.setattr(chat, "SIMILARITY_THRESHOLD", 0.30)
    yield
    chat.conversations.clear("test-email")


class TestAskEmailFlag:
    def test_email_available_when_no_sources(self, smtp_config, clear_history, monkeypatch):
        fake = FakeChat(returns="should not be used")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(chat, "search_documents", lambda q, limit=5: [])
        result = chat.ask("What is the dinner menu for Thursday?", session_id="test-email")
        assert result["sources"] == []
        assert result["email_available"] is True
        assert result["email_required"] is False
        assert "couldn't find reliable information" in result["answer"].lower()
        # No LLM round-trip when there is nothing to ground on.
        assert fake.calls == []

    def test_email_not_available_when_sources_answer(self, smtp_config, clear_history, monkeypatch):
        fake = FakeChat(returns="The WiFi password is Chitkara@2026.")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(
            chat,
            "search_documents",
            lambda q, limit=5: [
                fake_doc("The campus WiFi password is Chitkara@2026.", "it", 0.91)
            ],
        )
        result = chat.ask("What is the WiFi password?", session_id="test-email")
        assert result["email_available"] is False
        assert "Chitkara@2026" in result["answer"]

    def test_email_available_when_model_admits_gap(self, smtp_config, clear_history, monkeypatch):
        fake = FakeChat(
            returns="I don't have enough information to answer that question. "
            "Please contact the university helpdesk."
        )
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(
            chat,
            "search_documents",
            lambda q, limit=5: [fake_doc("Hostel rules overview", "hostel", 0.34)],
        )
        result = chat.ask("What time is mess open today?", session_id="test-email")
        assert result["email_available"] is True

    def test_email_flag_off_when_smtp_unconfigured(self, clear_history, monkeypatch):
        fake = FakeChat(returns="no idea")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(chat, "search_documents", lambda q, limit=5: [])
        result = chat.ask("Totally unknown subject?", session_id="test-email")
        assert result["email_available"] is False
        assert fake.calls == []