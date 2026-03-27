import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from app.core.config import settings
from app.services.tracing import traceable


@dataclass(slots=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    domain: str


@dataclass(slots=True)
class WebSearchResponse:
    results: list[WebSearchResult] = field(default_factory=list)
    error: str | None = None
    provider: str | None = None


def clean_text(value: str) -> str:
    return " ".join(value.split())


def decode_duckduckgo_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        destination = parse_qs(parsed.query).get("uddg", [value])[0]
        return unquote(destination)
    return value


class DuckDuckGoHTMLResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[WebSearchResult] = []
        self.current_href: str | None = None
        self.current_title: list[str] = []
        self.current_snippet: list[str] = []
        self.capture_title = False
        self.capture_snippet = False
        self._seen_urls: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class", "") or ""
        if tag == "a" and "result__a" in classes:
            self._commit_result()
            self.current_href = attributes.get("href")
            self.current_title = []
            self.current_snippet = []
            self.capture_title = True
            self.capture_snippet = False
            return

        if self.current_href and "result__snippet" in classes:
            self.capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if self.capture_title and tag == "a":
            self.capture_title = False
            return

        if self.capture_snippet and tag in {"a", "div"}:
            self.capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self.capture_title:
            self.current_title.append(data)
        elif self.capture_snippet:
            self.current_snippet.append(data)

    def close(self) -> None:
        super().close()
        self._commit_result()

    def _commit_result(self) -> None:
        if not self.current_href:
            return

        normalized_url = decode_duckduckgo_url(self.current_href)
        title = clean_text("".join(self.current_title))
        snippet = clean_text("".join(self.current_snippet))
        domain = urlparse(normalized_url).netloc.lower()
        if title and normalized_url and normalized_url not in self._seen_urls:
            self.results.append(
                WebSearchResult(
                    title=title,
                    url=normalized_url,
                    snippet=snippet,
                    domain=domain,
                )
            )
            self._seen_urls.add(normalized_url)

        self.current_href = None
        self.current_title = []
        self.current_snippet = []
        self.capture_title = False
        self.capture_snippet = False


def fetch_text_response(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> str:
    request = Request(url=url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urlopen(request, timeout=settings.web_search_timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def search_duckduckgo_html(query: str) -> WebSearchResponse:
    headers = {
        "User-Agent": settings.web_search_user_agent,
        "Accept-Language": "en-US,en;q=0.9",
    }
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    html = fetch_text_response(url, headers=headers)
    parser = DuckDuckGoHTMLResultsParser()
    parser.feed(html)
    parser.close()
    return WebSearchResponse(
        results=parser.results[: settings.web_search_max_results],
        provider="duckduckgo_html",
    )


def search_tavily(query: str) -> WebSearchResponse:
    if not settings.web_search_api_key:
        return WebSearchResponse(error="Missing WEB_SEARCH_API_KEY for Tavily", provider="tavily")

    payload = json.dumps(
        {
            "api_key": settings.web_search_api_key,
            "query": query,
            "max_results": settings.web_search_max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": settings.web_search_user_agent,
    }
    raw_response = fetch_text_response("https://api.tavily.com/search", data=payload, headers=headers)
    parsed = json.loads(raw_response)
    results = [
        WebSearchResult(
            title=clean_text(str(item.get("title", ""))),
            url=str(item.get("url", "")),
            snippet=clean_text(str(item.get("content", ""))),
            domain=urlparse(str(item.get("url", ""))).netloc.lower(),
        )
        for item in parsed.get("results", [])
        if item.get("url") and item.get("title")
    ]
    return WebSearchResponse(results=results[: settings.web_search_max_results], provider="tavily")


@traceable(name="web-search", run_type="chain")
def search_web(query: str) -> WebSearchResponse:
    if not settings.web_search_enabled:
        return WebSearchResponse(error="Web search is disabled", provider=settings.web_search_provider)

    provider = settings.web_search_provider.strip().lower()
    try:
        if provider == "tavily":
            return search_tavily(query)
        if provider == "duckduckgo_html":
            return search_duckduckgo_html(query)
        return WebSearchResponse(error=f"Unsupported web search provider: {settings.web_search_provider}", provider=provider)
    except (HTTPError, URLError, TimeoutError) as exc:
        return WebSearchResponse(error=str(exc), provider=provider)
    except Exception as exc:
        message = str(exc)
        if re.search(r"timed out", message, re.IGNORECASE):
            return WebSearchResponse(error=message, provider=provider)
        return WebSearchResponse(error=f"Web search failed: {message}", provider=provider)
