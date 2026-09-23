"""Tests for API-key verification and the rate limiter (no network)."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services.security import _SlidingWindowLimiter, client_ip, verify_api_key


def as_request(host, forwarded=None):
    headers = {}
    if forwarded:
        headers["X-Forwarded-For"] = forwarded
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


class TestClientIp:
    def test_direct_peer_used_without_proxy(self):
        settings.TRUSTED_PROXY_IPS_RAW = ""
        assert client_ip(as_request("1.2.3.4", "9.9.9.9")) == "1.2.3.4"

    def test_forwarded_used_when_peer_trusted(self):
        settings.TRUSTED_PROXY_IPS_RAW = "10.0.0.4"
        req = as_request("10.0.0.4", forwarded="203.0.113.5, 10.0.0.4")
        assert client_ip(req) == "203.0.113.5"

    def test_forwarded_ignored_when_peer_untrusted(self):
        settings.TRUSTED_PROXY_IPS_RAW = "10.0.0.4"
        req = as_request("5.5.5.5", forwarded="203.0.113.5")
        assert client_ip(req) == "5.5.5.5"


class TestVerifyApiKey:
    def test_disabled_auth(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEYS_RAW", "")
        assert verify_api_key(None) is None

    def test_valid_key(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEYS_RAW", "test-key-1")
        assert verify_api_key("test-key-1") is None

    def test_invalid_key_raises(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEYS_RAW", "test-key-1")
        with pytest.raises(HTTPException) as e:
            verify_api_key("wrong")
        assert e.value.status_code == 401


class TestSlidingWindowLimiter:
    def test_allow_up_to_limit_then_deny(self):
        limiter = _SlidingWindowLimiter()
        for _ in range(3):
            assert limiter.allow("k", limit=3, window=60) is True
        assert limiter.allow("k", limit=3, window=60) is False

    def test_window_expiry_frees_slot(self):
        limiter = _SlidingWindowLimiter()
        assert limiter.allow("k", limit=1, window=0.05) is True
        assert limiter.allow("k", limit=1, window=0.05) is False
        limiter._hits["k"][0] -= 1  # force age past the window
        assert limiter.allow("k", limit=1, window=0.05) is True

    def test_independent_keys(self):
        limiter = _SlidingWindowLimiter()
        assert limiter.allow("a", limit=1, window=60) is True
        assert limiter.allow("a", limit=1, window=60) is False
        assert limiter.allow("b", limit=1, window=60) is True

    def test_retry_after_reports_window(self):
        limiter = _SlidingWindowLimiter()
        limiter.allow("k", limit=1, window=30)
        assert limiter.retry_after("k", window=30) == 30