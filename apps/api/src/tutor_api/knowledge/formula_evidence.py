"""External formula evidence collected from fixed, auditable internet sources."""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

_SOURCE_MARKER = re.compile(r"^\[source:[^\]]+\]\s*$")
_FORMULA_SIGNAL = re.compile(r"=|\\frac|\\sum|\\sqrt|[∑√≈≤≥]")
_FORMULA_WORDS = re.compile(
    r"公式|方程|模型|定理|定律|formula|equation|model|theorem|law",
    re.IGNORECASE,
)
_ALLOWED_LANGUAGES = {"zh", "en"}


def extract_formula_search_queries(source_text: str, *, limit: int = 4) -> tuple[str, ...]:
    """Build bounded search queries from formula-adjacent textbook text."""

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be positive")
    lines = [
        " ".join(line.split())
        for line in source_text.splitlines()
        if line.strip() and not _SOURCE_MARKER.match(line.strip())
    ]
    queries: list[str] = []
    for index, line in enumerate(lines):
        if not (_FORMULA_SIGNAL.search(line) or _FORMULA_WORDS.search(line)):
            continue
        context = ""
        for previous in reversed(lines[max(0, index - 2) : index]):
            if not _FORMULA_SIGNAL.search(previous):
                context = previous
                break
        query = f"{context} {line}".strip() if context else line
        query = query[:300].strip()
        if query and query not in queries:
            queries.append(query)
        if len(queries) >= limit:
            break
    return tuple(queries)


class WikipediaFormulaEvidenceProvider:
    """Collect bounded Wikitext evidence from fixed Wikimedia API hosts."""

    def __init__(
        self,
        *,
        language: str = "zh",
        max_queries: int = 4,
        max_results_per_query: int = 2,
        max_excerpt_chars: int = 20_000,
        timeout_seconds: float = 15.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if language not in _ALLOWED_LANGUAGES:
            raise ValueError("unsupported Wikipedia language")
        for value, name in (
            (max_queries, "max_queries"),
            (max_results_per_query, "max_results_per_query"),
            (max_excerpt_chars, "max_excerpt_chars"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be positive")
        self._language = language
        self._endpoint = f"https://{language}.wikipedia.org/w/api.php"
        self._max_queries = max_queries
        self._max_results_per_query = max_results_per_query
        self._max_excerpt_chars = max_excerpt_chars
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def collect(self, source_text: str) -> tuple[dict[str, str], ...]:
        queries = extract_formula_search_queries(source_text, limit=self._max_queries)
        if not queries:
            return ()
        client = self._http_client or httpx.Client(
            timeout=self._timeout_seconds,
            headers={"User-Agent": "textbook-knowledge-platform/1.0 formula-evidence"},
        )
        close_client = self._http_client is None
        evidence: list[dict[str, str]] = []
        seen_titles: set[str] = set()
        try:
            for query in queries:
                for title in self._search_titles(client, query):
                    if title in seen_titles:
                        continue
                    seen_titles.add(title)
                    excerpt = self._read_wikitext(client, title)
                    if not excerpt:
                        continue
                    evidence.append(
                        {
                            "title": title,
                            "url": self._article_url(title),
                            "source_type": "encyclopedia",
                            "excerpt": excerpt,
                        }
                    )
            return tuple(evidence)
        except (httpx.HTTPError, TypeError, ValueError, KeyError):
            return ()
        finally:
            if close_client:
                client.close()

    def _search_titles(self, client: httpx.Client, query: str) -> tuple[str, ...]:
        response = client.get(
            self._endpoint,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srnamespace": "0",
                "srlimit": str(self._max_results_per_query),
                "format": "json",
                "formatversion": "2",
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("query", {}).get("search", [])
        if not isinstance(raw_results, list):
            raise ValueError("invalid Wikipedia search response")
        return tuple(
            title
            for item in raw_results[: self._max_results_per_query]
            if isinstance(item, dict)
            and isinstance((title := item.get("title")), str)
            and title.strip()
        )

    def _read_wikitext(self, client: httpx.Client, title: str) -> str:
        response = client.get(
            self._endpoint,
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "redirects": "1",
                "format": "json",
                "formatversion": "2",
            },
        )
        response.raise_for_status()
        payload = response.json()
        wikitext = payload.get("parse", {}).get("wikitext", "")
        if not isinstance(wikitext, str):
            raise ValueError("invalid Wikipedia parse response")
        return wikitext[: self._max_excerpt_chars].strip()

    def _article_url(self, title: str) -> str:
        slug = quote(title.replace(" ", "_"), safe="()_-")
        return f"https://{self._language}.wikipedia.org/wiki/{slug}"


__all__ = ["WikipediaFormulaEvidenceProvider", "extract_formula_search_queries"]