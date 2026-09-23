"""Tests for the RAG + web-grounding ask() flow (LLM + storage mocked)."""
import pytest

from app.config import settings
from app.services import chat
from tests.conftest import FakeChat


@pytest.fixture(autouse=True)
def isolate_environment(monkeypatch):
    # Never touch real Azure / web during tests.
    monkeypatch.setattr(settings, "WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "none")
    monkeypatch.setattr(chat, "SIMILARITY_THRESHOLD", 0.0)
    chat.conversations.clear("test-session")
    yield
    chat.conversations.clear("test-session")


def fake_doc(text, ns, score):
    return {"text": text, "metadata": {"agent_ns": ns}, "score": score}


class TestRewriteQuery:
    def test_falls_back_on_error(self, monkeypatch):
        fake = FakeChat(raises=RuntimeError("boom"))
        monkeypatch.setattr(chat, "client", fake)
        assert chat.rewrite_query("what about fees?", "some history") == (
            "what about fees?"
        )

    def test_uses_rewritten_output(self, monkeypatch):
        fake = FakeChat(returns="What is the re-evaluation fee?")
        monkeypatch.setattr(chat, "client", fake)
        out = chat.rewrite_query("what about the fee?", "some history")
        assert out == "What is the re-evaluation fee?"


class TestAsk:
    def test_basic_answer_with_sources(self, monkeypatch):
        fake = FakeChat(returns="The re-evaluation fee is Rs. 500.")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(
            chat,
            "search_documents",
            lambda q, limit=5: [fake_doc("Re-evaluation fee is Rs. 500.", "exams", 0.81)],
        )

        result = chat.ask("How much is re-evaluation?")

        assert "Rs. 500" in result["answer"]
        assert len(result["sources"]) == 1
        assert result["sources"][0]["metadata"]["agent_ns"] == "exams"
        assert result["session_id"] == "default"
        # exchange stored in memory
        hist = chat.conversations.get("default")
        assert len(hist) == 2 and hist[-1]["role"] == "assistant"

    def test_low_score_sources_filtered(self, monkeypatch):
        fake = FakeChat(returns="No idea.")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(chat, "SIMILARITY_THRESHOLD", 0.9)
        monkeypatch.setattr(
            chat,
            "search_documents",
            lambda q, limit=5: [fake_doc("irrelevant", "exams", 0.2)],
        )
        result = chat.ask("total fees")
        assert result["sources"] == []

    def test_web_grounding_added_when_enabled(self, monkeypatch):
        fake = FakeChat(returns="Answer with web.")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(
            chat,
            "search_documents",
            lambda q, limit=5: [],  # no local hits
        )
        # Make web retrieval active and deterministic.
        monkeypatch.setattr(settings, "WEB_SEARCH_ENABLED", True)
        monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "duckduckgo")
        monkeypatch.setattr(settings, "WEB_SEARCH_FALLBACK", True)
        web_results = [
            chat.web_search.WebResult(
                "Chitkara Admissions", "https://chitkara.example", "Admissions open"
            )
        ]
        monkeypatch.setattr(chat.web_search, "search_web", lambda q, limit=None: web_results)
        monkeypatch.setattr(
            chat.web_search, "fetch_page", lambda url, max_bytes=None: "page body"
        )

        result = chat.ask("admissions 2026 dates")

        assert result["sources"], "expected web sources"
        web_sources = [s for s in result["sources"] if s["metadata"].get("kind") == "web"]
        assert web_sources
        assert web_sources[0]["metadata"]["source_url"] == "https://chitkara.example"

    def test_web_fallback_skipped_when_local_found(self, monkeypatch):
        fake = FakeChat(returns="local answer")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(
            chat,
            "search_documents",
            lambda q, limit=5: [fake_doc("Local hostel info", "hostel", 0.85)],
        )
        monkeypatch.setattr(settings, "WEB_SEARCH_ENABLED", True)
        monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "duckduckgo")
        monkeypatch.setattr(settings, "WEB_SEARCH_FALLBACK", True)
        monkeypatch.setattr(chat.web_search, "search_web", lambda q, limit=None: [])
        monkeypatch.setattr(chat.web_search, "search_with_pages", lambda q: ([], []))

        result = chat.ask("hostel facilities")
        assert all(s["metadata"].get("kind") != "web" for s in result["sources"])

    def test_session_scoped_history(self, monkeypatch):
        fake = FakeChat(returns="answered")
        monkeypatch.setattr(chat, "client", fake)
        monkeypatch.setattr(chat, "search_documents", lambda q, limit=5: [])
        chat.ask("question one", session_id="sess-1")
        chat.ask("question two", session_id="sess-2")
        assert len(chat.conversations.get("sess-1")) == 2
        assert len(chat.conversations.get("sess-2")) == 2