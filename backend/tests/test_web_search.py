"""Tests for the web-search grounding helpers (network mocked)."""
from app.config import settings
from app.services import web_search as ws


class TestStripHtml:
    def test_tags_removed(self):
        assert ws._strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_entities_unescaped(self):
        assert ws._strip_html("a &amp; b") == "a & b"


class TestNormalizeHref:
    def test_duckduckgo_redirect_unwrapped(self):
        href = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fchitkara.edu.in%2F"
        assert ws.normalize_href(href) == "https://chitkara.edu.in/"

    def test_protocol_relative(self):
        assert ws.normalize_href("//example.com/x") == "https://example.com/x"

    def test_plain_url_passthrough(self):
        assert ws.normalize_href("https://example.com") == "https://example.com"


class TestFormatWebContext:
    def test_sections_include_url(self):
        results = [ws.WebResult("T", "https://x.example", "snippet here")]
        out = ws.format_web_context(results, [])
        assert "T" in out and "https://x.example" in out and "snippet here" in out

    def test_page_excerpts_appended(self):
        out = ws.format_web_context(
            [], [("https://x.example", "long page text")], )
        assert "web page excerpts" in out and "long page text" in out


class TestWebSourcesAreItems:
    def test_metadata(self):
        results = [ws.WebResult("My Title", "https://x.example", "snip")]
        items = ws.web_sources_as_items(results, [])
        assert items[0]["metadata"]["kind"] == "web"
        assert items[0]["metadata"]["source_url"] == "https://x.example"
        assert items[0]["metadata"]["agent_ns"] == "web"


class TestSearchWithPages:
    def test_combines_search_and_fetch(self, monkeypatch):
        monkeypatch.setattr(
            ws,
            "search_web",
            lambda q, limit=None: [
                ws.WebResult("A", "https://a.example", "snip a"),
                ws.WebResult("B", "https://b.example", "snip b"),
            ],
        )
        monkeypatch.setattr(
            ws, "fetch_page", lambda url, max_bytes=None: f"text for {url}"
        )
        results, pages = ws.search_with_pages("chitkara university")
        assert len(results) == 2
        assert len(pages) <= settings.WEB_PAGE_FETCH_LIMIT
        assert pages and pages[0][1].startswith("text for ")
        assert pages[0][0] == "https://a.example"

    def test_fetch_failures_skipped(self, monkeypatch):
        monkeypatch.setattr(
            ws,
            "search_web",
            lambda q, limit=None: [ws.WebResult("A", "https://a.example", "s")],
        )
        monkeypatch.setattr(ws, "fetch_page", lambda url, max_bytes=None: "")
        _, pages = ws.search_with_pages("chitkara")
        assert pages == []

    def test_provider_none_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "WEB_SEARCH_PROVIDER", "none")
        monkeypatch.setattr(settings, "WEB_SEARCH_ENABLED", True)
        assert ws.search_web("chitkara") == []