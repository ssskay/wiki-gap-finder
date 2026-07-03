"""Web search behind one swappable interface (spec: isolate the fragile bit).

Consumers on the Python side gather *coverage* sources. Default backend is DDG
(keyless). Firecrawl is opt-in (full-page markdown). The subagent chase in the
Claude layer uses its own tools and does not call this module.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from html import unescape

log = logging.getLogger("gap_finder.search")


@dataclass
class SearchResult:
    url: str
    title: str = ""
    text: str = ""

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "text": self.text}


class Backend:
    def search(self, query: str, limit: int) -> list[SearchResult]:  # pragma: no cover
        raise NotImplementedError


class FakeBackend(Backend):
    """Deterministic backend for tests. Matches on the first query keyword."""

    def __init__(self, table: dict[str, list[SearchResult]]):
        self._table = table

    def search(self, query: str, limit: int) -> list[SearchResult]:
        key = query.lower().split()[0] if query.split() else ""
        return self._table.get(key, [])[:limit]


class DDGBackend(Backend):
    """Keyless DuckDuckGo HTML-endpoint scraping. Fragile by nature — isolated."""

    ENDPOINT = "https://html.duckduckgo.com/html/"
    _LINK_RE = re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)

    def __init__(self, session):
        self._session = session  # a gap_finder.PoliteSession

    @classmethod
    def _parse(cls, html: str) -> list[SearchResult]:
        out: list[SearchResult] = []
        for url, title_html in cls._LINK_RE.findall(html):
            title = unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            out.append(SearchResult(url=url, title=title))
        return out

    def search(self, query: str, limit: int) -> list[SearchResult]:
        html = self._session.get_text(self.ENDPOINT, {"q": query})
        return self._parse(html)[:limit]


class FirecrawlBackend(Backend):
    """Opt-in backend shelling out to the `firecrawl` CLI for full-page markdown."""

    def __init__(self, binary: str = "firecrawl", runner=subprocess.run):
        self._binary = binary
        self._runner = runner

    def search(self, query: str, limit: int) -> list[SearchResult]:
        proc = self._runner([self._binary, "search", query, "--json", "--limit", str(limit)],
                            capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            log.warning("firecrawl search failed: %s", proc.stderr.strip())
            return []
        payload = json.loads(proc.stdout or "[]")
        rows = payload.get("data", payload) if isinstance(payload, dict) else payload
        return [SearchResult(url=r.get("url", ""), title=r.get("title", ""),
                             text=r.get("markdown", r.get("content", "")))
                for r in rows][:limit]


def search_web(query: str, backend: Backend, limit: int = 8) -> list[SearchResult]:
    """Single entry point. Callers pass an explicit backend (DI keeps it testable)."""
    log.debug("search_web: %r via %s", query, type(backend).__name__)
    return backend.search(query, limit)
