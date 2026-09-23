"""Web search grounding for the FAQ assistant.

Returns snippets (and optionally full page text) from the web about the
university so the assistant can answer questions not covered by the local
knowledge base. Only facts pulled from fetched content go into the context.

Providers:
    - duckduckgo : free HTML endpoint, no API key (default).
    - bing       : Azure Bing Web Search v7, requires BING_SEARCH_API_KEY.
    - wikipedia  : Wikimedia opensearch API, no API key.
    - none       : disables web grounding.
"""
import html
import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 "
    "university-faq-bot/1.0"
)

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str


def _strip_html(raw: str, limit: int = 1000) -> str:
    text = html.unescape(_TAG_RE.sub(" ", raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


class _TextExtractor(HTMLParser):
    """Pull visible text out of an HTML page, skipping scripts/styles."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []
        self._block_tags = {"p", "div", "li", "h1", "h2", "h3", "h4", "br", "tr"}

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "head"):
            self._skip += 1
        if tag in self._block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "head") and self._skip:
            self._skip -= 1
        if tag in self._block_tags:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _text_from_html(html_str: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html_str or "")
    except Exception:  # pragma: no cover - malformed html
        pass
    text = " ".join(" ".join(parser.parts).split())
    return text


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

def _duckduckgo(client: httpx.Client, query: str, limit: int) -> list[WebResult]:
    url = "https://html.duckduckgo.com/html/"
    resp = client.get(url, params={"q": query}, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()  # a 202 anomaly is treated as failure -> fallback
    page = resp.text

    results: list[WebResult] = []
    # Result anchors carry class="result__a ..." and class="result__snippet ..."
    # regardless of attribute order; parse tag-by-tag.
    tags = re.findall(
        r'<a(?=[^>]*class="[^"]*result__a[^"]*")[^>]*href="([^"]+)"[^>]*>(.*?)'
        r"</a>",
        page,
        re.DOTALL,
    )
    snippets = re.findall(
        r'<a(?=[^>]*class="[^"]*result__snippet[^"]*")[^>]*>(.*?)</a>',
        page,
        re.DOTALL,
    )
    for i, (href, title) in enumerate(tags[: limit]):
        results.append(
            WebResult(
                title=_strip_html(title, 200),
                url=html.unescape(href),
                snippet=_strip_html(
                    snippets[i] if i < len(snippets) else title, 500
                ),
            )
        )
    return results


def _bing(client: httpx.Client, query: str, limit: int) -> list[WebResult]:
    if not settings.BING_SEARCH_API_KEY:
        logger.warning("WEB_SEARCH_PROVIDER=bing but BING_SEARCH_API_KEY is unset")
        return []
    url = "https://api.bing.microsoft.com/v7.0/search"
    resp = client.get(
        url,
        params={"q": query, "count": limit},
        headers={"Ocp-Apim-Subscription-Key": settings.BING_SEARCH_API_KEY},
    )
    resp.raise_for_status()
    data = resp.json()
    results: list[WebResult] = []
    for item in (data.get("webPages") or {}).get("value", [])[:limit]:
        results.append(
            WebResult(
                title=item.get("name", ""),
                url=item.get("url", ""),
                snippet=_strip_html(item.get("snippet", ""), 500),
            )
        )
    return results


def _wikipedia(client: httpx.Client, query: str, limit: int) -> list[WebResult]:
    url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
        "origin": "*",
    }
    resp = client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    results: list[WebResult] = []
    for item in data.get("query", {}).get("search", [])[:limit]:
        title = item.get("title", "")
        results.append(
            WebResult(
                title=title,
                url=f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                snippet=_strip_html(item.get("snippet", ""), 500),
            )
        )
    return results


_PROVIDERS = {
    "duckduckgo": _duckduckgo,
    "bing": _bing,
    "wikipedia": _wikipedia,
}

# Providers tried automatically when the configured one fails or returns nothing.
# Wikipedia has no API key and is very reliable; DuckDuckGo's free HTML endpoint
# is unofficial and sometimes rate-limits (HTTP 202 anomaly).
_FALLBACK_SECONDARY = {
    "duckduckgo": ["wikipedia", "bing"],
    "bing": ["duckduckgo", "wikipedia"],
    "wikipedia": ["duckduckgo"],
}


def search_web(query: str, limit: int = None) -> list[WebResult]:
    """Run a web search and return top results (title, url, snippet).

    If the configured provider fails or returns nothing, falls back through the
    other supported providers so grounding rarely comes up empty.
    """
    provider = (settings.WEB_SEARCH_PROVIDER or "duckduckgo").lower()
    if provider == "none" or not settings.WEB_SEARCH_ENABLED:
        return []
    limit = limit or settings.WEB_SEARCH_RESULT_LIMIT

    chain = [provider] + _FALLBACK_SECONDARY.get(provider, [])
    timeout = httpx.Timeout(8.0, connect=5.0)
    for name in chain:
        handler = _PROVIDERS.get(name)
        if not handler:
            continue
        # Providers that need a key are skipped unless one is configured.
        if name == "bing" and not settings.BING_SEARCH_API_KEY:
            continue
        try:
            with httpx.Client(
                timeout=timeout,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            ) as client:
                results = handler(client, query, limit)
            if results:
                if name != provider:
                    logger.info("Web search fell back %s -> %s for %r", provider, name, query)
                logger.info("Web search(%s) returned %d results for %r", name, len(results), query)
                return results
            logger.info("Web search(%s) returned no results for %r", name, query)
        except Exception as e:  # pragma: no cover - network/provider issues
            logger.warning("Web search (%s) failed for %r: %s", name, query, e)
    return []


def fetch_page(url: str, max_bytes: int = None) -> str:
    """Fetch a page and return its visible text, truncated to max_bytes chars."""
    if not settings.WEB_PAGE_FETCH_ENABLED:
        return ""
    max_bytes = max_bytes or settings.WEB_PAGE_FETCH_MAX_BYTES
    try:
        with httpx.Client(
            timeout=httpx.Timeout(10.0, connect=6.0),
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content = resp.content[: max_bytes * 2]
        text = _text_from_html(content.decode("utf-8", errors="replace"))
        return text[:max_bytes]
    except Exception as e:  # pragma: no cover - network/provider issues
        logger.warning("Page fetch failed for %s: %s", url, e)
        return ""


def format_web_context(results: list[WebResult], pages: list[tuple]) -> str:
    """Render web results into the prompt context block."""
    sections = []
    for i, res in enumerate(results, 1):
        sections.append(
            f"[{i}] {res.title}\nURL: {res.url}\n{res.snippet}"
        )
    if pages and any(t for _, t in pages):
        sections.append("\n--- web page excerpts ---")
        for url, text in pages:
            if text:
                sections.append(f"{url}\n{text}")
    return "\n\n".join(sections)


def web_sources_as_items(results: list[WebResult], pages: list[tuple]) -> list[dict]:
    """Turn search results into SourceItem-shaped dicts for the API response."""
    return [
        {
            "text": res.snippet,
            "metadata": {
                "agent_ns": "web",
                "kind": "web",
                "title": res.title,
                "source_url": res.url,
            },
            "score": 0.0,
        }
        for res in results
    ]


def normalize_href(href: str) -> str:
    """DDG returns redirect URLs; unwrap the real destination when present."""
    if href.startswith("//"):
        return f"https:{href}"
    if "uddg=" in href:
        qs = parse_qs(urlsplit(href).query)
        if "uddg" in qs:
            return qs["uddg"][0]
    return href


def search_with_pages(query: str, result_limit: int = None, page_fetch_limit: int = None) -> tuple[list[WebResult], list[tuple]]:
    """Search and fetch top page text; used by chat to build grounded context."""
    results = search_web(query, limit=result_limit)
    fetch_limit = page_fetch_limit or settings.WEB_PAGE_FETCH_LIMIT
    pages: list[tuple] = []
    for res in results[:fetch_limit]:
        real_url = normalize_href(res.url)
        text = fetch_page(real_url)
        if text:
            pages.append((real_url, text))
    return results, pages