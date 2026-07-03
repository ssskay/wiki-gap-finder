# Source Vetter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a source-vetting component to Wikipedia Gap Finder that classifies sources by Wikipedia reliability, traces breadcrumbs to a VERIFIED / LEAD / DEAD_END verdict, and merges verdicts into the dossier — with a hard WP:SYNTH guardrail and BLP handling.

**Architecture:** Two processes across a two-file JSON boundary. Python (keyless) builds `vetting_worklist.json` (sources + RSP tiers + seed claims) and later renders `vetting_verdicts.json` into the dossier. A Claude subagent reads the worklist, does the reasoning/chasing, and writes the verdicts. The contract is the two JSON files; each side is testable without the other.

**Tech Stack:** Python 3.12, `requests`, `PyYAML`, `jsonschema` (validation), `pytest` (tests), the `firecrawl` CLI (optional chase backend), DuckDuckGo HTML (keyless fallback).

---

## Reconciliation note (read before Task 1)

The spec's "one swappable `search_web()` function" has **two consumers**, and the plan keeps them distinct:

- **Python coverage gathering** (Task 4's `search_web`): used when building a worklist. Default backend **DDG** (keyless, so the tool still runs with zero setup); **Firecrawl** available as an opt-in backend.
- **Subagent chase** (Task 9): the Claude vetter chases breadcrumbs using its *own native tools* (Firecrawl skill / WebSearch), governed by the same caps. Sara's "Firecrawl as default chase backend" applies here — the chase is Firecrawl-first.

So: Firecrawl is the default for the *chase* (subagent), DDG is the zero-dependency default for Python's *coverage* function. Both are behind clean interfaces.

## File structure

```
gap_finder.py                       # CLI entry — MODIFIED for integration only
gapfinder/
  __init__.py
  contract.py                       # load schemas; validate_worklist / validate_verdicts
  rsp.py                            # reliability tiering (curated seed + best-effort refresh)
  search.py                        # search_web() + FakeBackend / DDGBackend / FirecrawlBackend
  worklist.py                      # build_worklist() -> validated dict; write_worklist()
  verdicts.py                      # load_verdicts(path) -> validated dict
  dossier.py                       # render_dossier(verdicts, subject) -> markdown
  schemas/
    worklist.schema.json
    verdicts.schema.json
data/
  rsp_seed.json                     # curated domain -> {tier, note}
skills/vet-sources/SKILL.md         # subagent contract (the Claude layer)
tests/
  conftest.py
  fixtures/
    ddg_result.html
    verdicts_sample.json
    worklist_sample.json
  test_contract.py
  test_rsp.py
  test_search.py
  test_worklist.py
  test_verdicts.py
  test_dossier.py
  test_cli_integration.py
```

New Python modules import shared primitives (`PoliteSession`, `Campaign`, API constants) from the existing `gap_finder` module — it is import-safe (all execution is under `if __name__ == "__main__"`). No refactor of the approved Stages 1–2 code.

---

### Task 1: Project setup (git, package skeleton, test harness)

**Files:**
- Create: `.gitignore`, `gapfinder/__init__.py`, `tests/conftest.py`, `pytest.ini`

- [ ] **Step 1: Initialize git and ignore generated dirs**

```bash
cd /Users/sarakay/wiki-gap-finder
git init
```

Create `.gitignore`:

```gitignore
__pycache__/
*.pyc
output/
data/rsp_cache.json
.pytest_cache/
```

- [ ] **Step 2: Create the package and pytest config**

Create `gapfinder/__init__.py`:

```python
"""gapfinder — source-vetting components for Wikipedia Gap Finder."""
```

Create `pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -q
```

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

# Make the project root importable so tests can `import gapfinder` and `import gap_finder`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
```

- [ ] **Step 3: Verify pytest collects nothing yet (no tests) without error**

Run: `python3 -m pytest`
Expected: `no tests ran` (exit code 5) — confirms config loads.

- [ ] **Step 4: Commit**

```bash
git add .gitignore gapfinder/__init__.py pytest.ini tests/conftest.py gap_finder.py campaigns input docs
git commit -m "chore: init git, package skeleton, pytest harness"
```

---

### Task 2: JSON contract (schemas + validation)

**Files:**
- Create: `gapfinder/schemas/worklist.schema.json`, `gapfinder/schemas/verdicts.schema.json`, `gapfinder/contract.py`
- Test: `tests/test_contract.py`, `tests/fixtures/worklist_sample.json`, `tests/fixtures/verdicts_sample.json`

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/worklist_sample.json`:

```json
{
  "campaign": "disability-pride-2026",
  "subject": {"name": "Corina Boettger", "aliases": [], "wikidata_id": "Q1", "known_for_hint": "voice actor"},
  "sources": [
    {"source_id": "s1", "url": "https://ex.com/a", "domain": "ex.com", "title": "A",
     "rsp_tier": "GENERALLY_RELIABLE", "rsp_note": "", "fetched_text": "text", "discovery": "coverage_search"}
  ],
  "seed_claims": [
    {"claim_id": "c1", "text": "Won XYZ award", "from_source_id": "s1", "claim_type": "award", "contentious": false}
  ]
}
```

Create `tests/fixtures/verdicts_sample.json`:

```json
{
  "campaign": "disability-pride-2026",
  "subject_name": "Corina Boettger",
  "generated_by": "claude-source-vetter",
  "verdicts": [
    {"claim_id": "c2", "claim_text": "Voiced Paimon", "bucket": "VERIFIED", "claim_type": "role",
     "contentious": false,
     "supporting": [{"source_id": "s1", "url": "https://ex.com/a", "rsp_tier": "GENERALLY_RELIABLE",
                     "quote": "Boettger voices Paimon."}],
     "lead": null, "reasoning": "single reliable source",
     "chase_log": {"searches_run": 0, "pages_fetched": 0, "capped": false}},
    {"claim_id": "c1", "claim_text": "Won XYZ award", "bucket": "LEAD", "claim_type": "award",
     "contentious": false, "supporting": [],
     "lead": {"breadcrumb_source": {"url": "https://fandom.com/x", "rsp_tier": "USER_GENERATED"},
              "partial_corroboration": [{"url": "https://news.com/y", "quote": "XYZ award went to production Y.",
                                          "note": "does not name subject"}],
              "missing": "a reliable source naming Corina Boettger with the XYZ award",
              "suggested_searches": ["\"Corina Boettger\" XYZ award"]},
     "reasoning": "no reliable source connects subject to award",
     "chase_log": {"searches_run": 3, "pages_fetched": 2, "capped": false}}
  ],
  "summary": {"verified": 1, "lead": 1, "dead_end": 0}
}
```

Create `tests/test_contract.py`:

```python
import json
import pytest
from jsonschema.exceptions import ValidationError
from gapfinder import contract
from tests.conftest import FIXTURES


def test_valid_worklist_passes():
    data = json.loads((FIXTURES / "worklist_sample.json").read_text())
    contract.validate_worklist(data)  # must not raise


def test_valid_verdicts_passes():
    data = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    contract.validate_verdicts(data)  # must not raise


def test_verified_without_quote_is_rejected():
    data = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    data["verdicts"][0]["supporting"] = []  # VERIFIED with no supporting source
    with pytest.raises(ValidationError):
        contract.validate_verdicts(data)


def test_unknown_bucket_is_rejected():
    data = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    data["verdicts"][0]["bucket"] = "MAYBE"
    with pytest.raises(ValidationError):
        contract.validate_verdicts(data)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: gapfinder.contract`.

- [ ] **Step 3: Write the schemas and validator**

Create `gapfinder/schemas/worklist.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["campaign", "subject", "sources", "seed_claims"],
  "properties": {
    "campaign": {"type": "string"},
    "subject": {
      "type": "object",
      "required": ["name"],
      "properties": {
        "name": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "wikidata_id": {"type": ["string", "null"]},
        "known_for_hint": {"type": "string"}
      }
    },
    "sources": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["source_id", "url", "domain", "rsp_tier"],
        "properties": {
          "source_id": {"type": "string"},
          "url": {"type": "string"},
          "domain": {"type": "string"},
          "title": {"type": "string"},
          "rsp_tier": {"$ref": "#/definitions/tier"},
          "rsp_note": {"type": "string"},
          "fetched_text": {"type": "string"},
          "discovery": {"type": "string"}
        }
      }
    },
    "seed_claims": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_id", "text"],
        "properties": {
          "claim_id": {"type": "string"},
          "text": {"type": "string"},
          "from_source_id": {"type": ["string", "null"]},
          "claim_type": {"type": "string"},
          "contentious": {"type": "boolean"}
        }
      }
    }
  },
  "definitions": {
    "tier": {"enum": ["GENERALLY_RELIABLE", "MARGINAL", "GENERALLY_UNRELIABLE",
                       "DEPRECATED", "USER_GENERATED", "UNRATED"]}
  }
}
```

Create `gapfinder/schemas/verdicts.schema.json`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["campaign", "subject_name", "verdicts", "summary"],
  "properties": {
    "campaign": {"type": "string"},
    "subject_name": {"type": "string"},
    "generated_by": {"type": "string"},
    "summary": {
      "type": "object",
      "required": ["verified", "lead", "dead_end"],
      "properties": {
        "verified": {"type": "integer"},
        "lead": {"type": "integer"},
        "dead_end": {"type": "integer"}
      }
    },
    "verdicts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim_id", "claim_text", "bucket", "supporting", "reasoning"],
        "properties": {
          "claim_id": {"type": "string"},
          "claim_text": {"type": "string"},
          "bucket": {"enum": ["VERIFIED", "LEAD", "DEAD_END"]},
          "claim_type": {"type": "string"},
          "contentious": {"type": "boolean"},
          "supporting": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["url", "rsp_tier", "quote"],
              "properties": {
                "source_id": {"type": "string"},
                "url": {"type": "string"},
                "rsp_tier": {"$ref": "#/definitions/tier"},
                "quote": {"type": "string", "minLength": 1}
              }
            }
          },
          "lead": {
            "oneOf": [
              {"type": "null"},
              {
                "type": "object",
                "required": ["breadcrumb_source", "missing"],
                "properties": {
                  "breadcrumb_source": {"type": "object"},
                  "partial_corroboration": {"type": "array"},
                  "missing": {"type": "string"},
                  "suggested_searches": {"type": "array", "items": {"type": "string"}}
                }
              }
            ]
          },
          "reasoning": {"type": "string"},
          "chase_log": {"type": "object"}
        },
        "allOf": [
          {
            "if": {"properties": {"bucket": {"const": "VERIFIED"}}},
            "then": {"properties": {"supporting": {"minItems": 1}}}
          }
        ]
      }
    }
  },
  "definitions": {
    "tier": {"enum": ["GENERALLY_RELIABLE", "MARGINAL", "GENERALLY_UNRELIABLE",
                       "DEPRECATED", "USER_GENERATED", "UNRATED"]}
  }
}
```

Create `gapfinder/contract.py`:

```python
"""Load and validate the two JSON-contract files (worklist + verdicts)."""
import json
from pathlib import Path
from jsonschema import Draft7Validator

_SCHEMA_DIR = Path(__file__).parent / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text())


_WORKLIST_VALIDATOR = Draft7Validator(_load_schema("worklist.schema.json"))
_VERDICTS_VALIDATOR = Draft7Validator(_load_schema("verdicts.schema.json"))


def validate_worklist(data: dict) -> None:
    """Raise jsonschema.ValidationError if the worklist is malformed."""
    _WORKLIST_VALIDATOR.validate(data)


def validate_verdicts(data: dict) -> None:
    """Raise jsonschema.ValidationError if the verdicts file is malformed.

    Structurally enforces: bucket is a known value, and VERIFIED requires at
    least one supporting source, each of which requires a non-empty quote.
    """
    _VERDICTS_VALIDATOR.validate(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_contract.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add gapfinder/schemas gapfinder/contract.py tests/test_contract.py tests/fixtures/worklist_sample.json tests/fixtures/verdicts_sample.json
git commit -m "feat: JSON contract schemas + validation for worklist/verdicts"
```

---

### Task 3: Reliability tiering (RSP)

**Files:**
- Create: `data/rsp_seed.json`, `gapfinder/rsp.py`
- Test: `tests/test_rsp.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_rsp.py`:

```python
from gapfinder import rsp


def test_known_reliable_domain():
    assert rsp.tier_for_domain("nytimes.com")[0] == "GENERALLY_RELIABLE"


def test_user_generated_fandom():
    assert rsp.tier_for_domain("genshin-impact.fandom.com")[0] == "USER_GENERATED"


def test_www_and_subdomain_are_normalized():
    assert rsp.tier_for_domain("www.nytimes.com")[0] == "GENERALLY_RELIABLE"


def test_unknown_domain_is_unrated():
    assert rsp.tier_for_domain("some-random-blog-42.example")[0] == "UNRATED"


def test_tier_for_url_extracts_domain():
    assert rsp.tier_for_url("https://www.imdb.com/name/nm123/")[0] == "GENERALLY_UNRELIABLE"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_rsp.py -v`
Expected: FAIL — `ModuleNotFoundError: gapfinder.rsp`.

- [ ] **Step 3: Write the curated seed and the tiering module**

Create `data/rsp_seed.json` (curated subset of WP:RSP — authoritative for common domains; extend via refresh):

```json
{
  "nytimes.com": {"tier": "GENERALLY_RELIABLE", "note": "The New York Times"},
  "bbc.com": {"tier": "GENERALLY_RELIABLE", "note": "BBC News"},
  "bbc.co.uk": {"tier": "GENERALLY_RELIABLE", "note": "BBC News"},
  "theguardian.com": {"tier": "GENERALLY_RELIABLE", "note": "The Guardian"},
  "washingtonpost.com": {"tier": "GENERALLY_RELIABLE", "note": "The Washington Post"},
  "reuters.com": {"tier": "GENERALLY_RELIABLE", "note": "Reuters"},
  "apnews.com": {"tier": "GENERALLY_RELIABLE", "note": "Associated Press"},
  "npr.org": {"tier": "GENERALLY_RELIABLE", "note": "NPR"},
  "nature.com": {"tier": "GENERALLY_RELIABLE", "note": "Nature"},
  "imdb.com": {"tier": "GENERALLY_UNRELIABLE", "note": "IMDb — user-editable, not reliable"},
  "kickstarter.com": {"tier": "GENERALLY_UNRELIABLE", "note": "self-published crowdfunding"},
  "dailymail.co.uk": {"tier": "DEPRECATED", "note": "Daily Mail — deprecated"},
  "medium.com": {"tier": "GENERALLY_UNRELIABLE", "note": "self-published blog platform"},
  "substack.com": {"tier": "GENERALLY_UNRELIABLE", "note": "self-published newsletter platform"},
  "fandom.com": {"tier": "USER_GENERATED", "note": "Fandom/Wikia — user-generated wiki"},
  "wikipedia.org": {"tier": "USER_GENERATED", "note": "Wikipedia is not a reliable source for itself"},
  "reddit.com": {"tier": "USER_GENERATED", "note": "forum, user-generated"},
  "youtube.com": {"tier": "MARGINAL", "note": "depends on uploader; often not independent"},
  "linkedin.com": {"tier": "MARGINAL", "note": "self-published profile data"}
}
```

Create `gapfinder/rsp.py`:

```python
"""Reliability tiering against Wikipedia's perennial-sources list (WP:RSP).

Keyless. Uses a bundled curated seed (data/rsp_seed.json) as the authoritative
map for common domains; unknown domains return UNRATED so the subagent judges
them from first principles. refresh_from_wikipedia() is a best-effort augment.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("gap_finder.rsp")

_SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "rsp_seed.json"
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "rsp_cache.json"

UNRATED = ("UNRATED", "")


def _load_map() -> dict[str, dict]:
    data: dict[str, dict] = {}
    if _SEED_PATH.exists():
        data.update(json.loads(_SEED_PATH.read_text()))
    if _CACHE_PATH.exists():  # refreshed entries override/extend the seed
        data.update(json.loads(_CACHE_PATH.read_text()))
    return data


_MAP = _load_map()


def _candidate_domains(domain: str) -> list[str]:
    """Yield the domain and its parent domains, so 'x.fandom.com' matches
    the 'fandom.com' seed entry. Strips a leading 'www.'."""
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    parts = domain.split(".")
    return [".".join(parts[i:]) for i in range(len(parts) - 1)]


def tier_for_domain(domain: str) -> tuple[str, str]:
    """Return (tier, note) for a domain. Checks the domain and its parents;
    the most specific match wins. Unknown -> UNRATED."""
    for cand in _candidate_domains(domain):
        if cand in _MAP:
            entry = _MAP[cand]
            return entry["tier"], entry.get("note", "")
    return UNRATED


def tier_for_url(url: str) -> tuple[str, str]:
    return tier_for_domain(urlparse(url).netloc)


def refresh_from_wikipedia(session) -> int:
    """Best-effort: fetch the RSP page and merge any parsed rows into the cache.
    Returns the number of entries written. Failures are logged, not raised."""
    try:
        from gap_finder import ENWIKI_API  # shared endpoint + session
        data = session.get_json(ENWIKI_API, {
            "action": "parse", "page": "Wikipedia:Reliable sources/Perennial sources",
            "prop": "wikitext", "format": "json", "formatversion": "2",
        })
        wikitext = data.get("parse", {}).get("wikitext", "")
        parsed = _parse_rsp_wikitext(wikitext)
        if parsed:
            merged = json.loads(_CACHE_PATH.read_text()) if _CACHE_PATH.exists() else {}
            merged.update(parsed)
            _CACHE_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
            log.info("rsp: cached %d parsed entries", len(parsed))
        return len(parsed)
    except Exception as exc:  # best-effort; the seed still covers common domains
        log.warning("rsp refresh failed (using seed only): %s", exc)
        return 0


def _parse_rsp_wikitext(wikitext: str) -> dict[str, dict]:
    """Best-effort parse. The RSP table is complex; we extract nothing risky
    here and rely on the curated seed. This hook exists so a richer parser can
    drop in later without changing callers. Returns {} for now."""
    return {}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_rsp.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add data/rsp_seed.json gapfinder/rsp.py tests/test_rsp.py
git commit -m "feat: keyless RSP reliability tiering with curated seed"
```

---

### Task 4: Search backend interface

**Files:**
- Create: `gapfinder/search.py`
- Test: `tests/test_search.py`, `tests/fixtures/ddg_result.html`

- [ ] **Step 1: Write the failing test**

Create `tests/fixtures/ddg_result.html` (minimal DuckDuckGo HTML-endpoint shape):

```html
<html><body>
<div class="result">
  <a class="result__a" href="https://news.com/story-1">Story One Title</a>
  <a class="result__snippet">Snippet one.</a>
</div>
<div class="result">
  <a class="result__a" href="https://blog.example/story-2">Story Two Title</a>
  <a class="result__snippet">Snippet two.</a>
</div>
</body></html>
```

Create `tests/test_search.py`:

```python
from gapfinder import search
from tests.conftest import FIXTURES


def test_fake_backend_returns_seeded_results():
    backend = search.FakeBackend({"corina": [
        search.SearchResult(url="https://x.com", title="X", text="body")]})
    results = search.search_web("corina award", backend=backend)
    assert results[0].url == "https://x.com"
    assert results[0].text == "body"


def test_ddg_html_is_parsed_into_results():
    html = (FIXTURES / "ddg_result.html").read_text()
    results = search.DDGBackend._parse(html)
    assert [r.url for r in results] == ["https://news.com/story-1", "https://blog.example/story-2"]
    assert results[0].title == "Story One Title"


def test_search_result_roundtrips_to_dict():
    r = search.SearchResult(url="https://x.com", title="T", text="B")
    assert r.to_dict() == {"url": "https://x.com", "title": "T", "text": "B"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_search.py -v`
Expected: FAIL — `ModuleNotFoundError: gapfinder.search`.

- [ ] **Step 3: Write the search module**

Create `gapfinder/search.py`:

```python
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
from dataclasses import dataclass, field
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
```

- [ ] **Step 4: Add `get_text` to the shared session**

Modify `gap_finder.py` — add a method to `PoliteSession` (after `get_json`). This mirrors `get_json` but returns raw text, for DDG HTML:

```python
    def get_text(self, url: str, params: dict[str, Any]) -> str:
        """GET a text/HTML endpoint with the same rate limiting and backoff."""
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                log.debug("GET(text) %s params=%s (attempt %d)", url, params, attempt)
                resp = self._session.get(url, params=params, timeout=30)
                self._last_request_ts = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                last_err = exc
                self._last_request_ts = time.monotonic()
                backoff = BACKOFF_BASE ** attempt
                log.warning("request failed (%s); backoff %.1fs then retry %d/%d",
                            exc, backoff, attempt, MAX_RETRIES)
                time.sleep(backoff)
        raise RuntimeError(f"request to {url} failed after {MAX_RETRIES} attempts: {last_err}")
```

- [ ] **Step 5: Run to verify it passes**

Run: `python3 -m pytest tests/test_search.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add gapfinder/search.py tests/test_search.py tests/fixtures/ddg_result.html gap_finder.py
git commit -m "feat: search_web interface with Fake/DDG/Firecrawl backends"
```

---

### Task 5: Worklist builder

**Files:**
- Create: `gapfinder/worklist.py`
- Test: `tests/test_worklist.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_worklist.py`:

```python
from gapfinder import worklist, contract, search


def test_build_worklist_tiers_sources_and_validates():
    sources = [
        search.SearchResult(url="https://www.nytimes.com/a", title="NYT piece", text="body one"),
        search.SearchResult(url="https://genshin.fandom.com/x", title="Fan wiki", text="won XYZ award"),
    ]
    wl = worklist.build_worklist(
        campaign="disability-pride-2026",
        subject={"name": "Corina Boettger", "wikidata_id": "Q1"},
        coverage=sources,
        seed_claims=[],
    )
    contract.validate_worklist(wl)  # must not raise
    tiers = {s["domain"]: s["rsp_tier"] for s in wl["sources"]}
    assert tiers["nytimes.com"] == "GENERALLY_RELIABLE"
    assert tiers["genshin.fandom.com"] == "USER_GENERATED"
    assert wl["sources"][0]["source_id"] == "s1"
    assert wl["sources"][0]["fetched_text"] == "body one"


def test_write_and_reload(tmp_path):
    wl = worklist.build_worklist("c", {"name": "N"}, [], [])
    path = worklist.write_worklist(tmp_path, wl)
    assert path.exists()
    import json
    contract.validate_worklist(json.loads(path.read_text()))
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_worklist.py -v`
Expected: FAIL — `ModuleNotFoundError: gapfinder.worklist`.

- [ ] **Step 3: Write the worklist builder**

Create `gapfinder/worklist.py`:

```python
"""Assemble a vetting_worklist.json from coverage sources + seed claims."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from gapfinder import rsp
from gapfinder.search import SearchResult


def build_worklist(campaign: str, subject: dict,
                   coverage: list[SearchResult], seed_claims: list[dict]) -> dict:
    """Build a validated-shape worklist dict. Each coverage source gets an id
    and an RSP tier; seed_claims are passed through (may be empty)."""
    subject = {
        "name": subject["name"],
        "aliases": subject.get("aliases", []),
        "wikidata_id": subject.get("wikidata_id"),
        "known_for_hint": subject.get("known_for_hint", ""),
    }
    sources = []
    for i, r in enumerate(coverage, start=1):
        domain = urlparse(r.url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        tier, note = rsp.tier_for_url(r.url)
        sources.append({
            "source_id": f"s{i}",
            "url": r.url,
            "domain": domain,
            "title": r.title,
            "rsp_tier": tier,
            "rsp_note": note,
            "fetched_text": r.text,
            "discovery": "coverage_search",
        })
    return {
        "campaign": campaign,
        "subject": subject,
        "sources": sources,
        "seed_claims": seed_claims,
    }


def write_worklist(out_dir: Path, worklist: dict) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "vetting_worklist.json"
    path.write_text(json.dumps(worklist, indent=2, ensure_ascii=False))
    return path
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_worklist.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add gapfinder/worklist.py tests/test_worklist.py
git commit -m "feat: worklist builder with RSP tiering of coverage sources"
```

---

### Task 6: Verdicts loader

**Files:**
- Create: `gapfinder/verdicts.py`
- Test: `tests/test_verdicts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_verdicts.py`:

```python
import json
import pytest
from jsonschema.exceptions import ValidationError
from gapfinder import verdicts
from tests.conftest import FIXTURES


def test_load_valid_verdicts(tmp_path):
    src = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    p = tmp_path / "vetting_verdicts.json"
    p.write_text(json.dumps(src))
    loaded = verdicts.load_verdicts(p)
    assert loaded["summary"]["verified"] == 1
    assert {v["bucket"] for v in loaded["verdicts"]} == {"VERIFIED", "LEAD"}


def test_load_rejects_invalid(tmp_path):
    bad = {"campaign": "c"}  # missing required fields
    p = tmp_path / "vetting_verdicts.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValidationError):
        verdicts.load_verdicts(p)


def test_by_bucket_groups_claims():
    src = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    grouped = verdicts.by_bucket(src)
    assert len(grouped["VERIFIED"]) == 1
    assert len(grouped["LEAD"]) == 1
    assert grouped["DEAD_END"] == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_verdicts.py -v`
Expected: FAIL — `ModuleNotFoundError: gapfinder.verdicts`.

- [ ] **Step 3: Write the loader**

Create `gapfinder/verdicts.py`:

```python
"""Load and group the subagent's vetting_verdicts.json."""
from __future__ import annotations

import json
from pathlib import Path

from gapfinder import contract

BUCKETS = ("VERIFIED", "LEAD", "DEAD_END")


def load_verdicts(path) -> dict:
    """Load + schema-validate a verdicts file. Raises ValidationError if bad."""
    data = json.loads(Path(path).read_text())
    contract.validate_verdicts(data)
    return data


def by_bucket(verdicts_data: dict) -> dict[str, list[dict]]:
    """Group verdicts by bucket, always returning all three keys."""
    grouped: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for v in verdicts_data.get("verdicts", []):
        grouped.setdefault(v["bucket"], []).append(v)
    return grouped
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_verdicts.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add gapfinder/verdicts.py tests/test_verdicts.py
git commit -m "feat: verdicts loader with schema validation + bucket grouping"
```

---

### Task 7: Dossier renderer

**Files:**
- Create: `gapfinder/dossier.py`
- Test: `tests/test_dossier.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dossier.py`:

```python
import json
from gapfinder import dossier, verdicts
from tests.conftest import FIXTURES


def _sample():
    return json.loads((FIXTURES / "verdicts_sample.json").read_text())


def test_verified_claim_renders_in_facts_table_with_quote():
    md = dossier.render_dossier(_sample(), subject={"name": "Corina Boettger"})
    assert "## Verified facts" in md
    assert "Voiced Paimon" in md
    assert "Boettger voices Paimon." in md
    assert "https://ex.com/a" in md


def test_lead_renders_in_research_leads_not_table():
    md = dossier.render_dossier(_sample(), subject={"name": "Corina Boettger"})
    assert "## Research leads" in md
    # The SYNTH-trapped claim must NOT appear as a verified fact row.
    facts_section = md.split("## Research leads")[0]
    assert "Won XYZ award" not in facts_section
    assert "a reliable source naming Corina Boettger with the XYZ award" in md


def test_blp_banner_present_when_any_contentious(tmp_path):
    data = _sample()
    data["verdicts"][0]["contentious"] = True
    md = dossier.render_dossier(data, subject={"name": "Corina Boettger"})
    assert "BLP" in md


def test_prose_constraint_notice_present():
    md = dossier.render_dossier(_sample(), subject={"name": "Corina Boettger"})
    assert "does not write article prose" in md.lower() or "write every sentence" in md.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_dossier.py -v`
Expected: FAIL — `ModuleNotFoundError: gapfinder.dossier`.

- [ ] **Step 3: Write the renderer**

Create `gapfinder/dossier.py`:

```python
"""Render a verdicts dict into the human-facing dossier markdown.

Structure only — never prose. Maps buckets to sections:
  VERIFIED -> Verified facts table (claim | source | quote)
  LEAD     -> Research leads (chase before writing)
  DEAD_END -> UNVERIFIED — do not use
"""
from __future__ import annotations

from gapfinder import verdicts as verdicts_mod

_PROSE_NOTICE = (
    "> This dossier does not write article prose. Every fact below traces to a "
    "verbatim quote from a reliable source. You write every sentence."
)


def render_dossier(verdicts_data: dict, subject: dict) -> str:
    name = subject.get("name", verdicts_data.get("subject_name", "Unknown"))
    grouped = verdicts_mod.by_bucket(verdicts_data)
    contentious = any(v.get("contentious") for v in verdicts_data.get("verdicts", []))

    lines: list[str] = [f"# Dossier: {name}", "", _PROSE_NOTICE, ""]

    if contentious:
        lines += ["> **BLP:** contains contentious claims about a living person. "
                  "Contentious facts require a generally-reliable source or they are dropped, "
                  "not hedged.", ""]

    # VERIFIED
    lines += ["## Verified facts", ""]
    verified = grouped["VERIFIED"]
    if verified:
        lines += ["| Claim | Source | Quote |", "| --- | --- | --- |"]
        for v in verified:
            for s in v["supporting"]:
                quote = s["quote"].replace("|", "\\|")
                claim = v["claim_text"].replace("|", "\\|")
                lines.append(f"| {claim} | {s['url']} | \"{quote}\" |")
    else:
        lines.append("_No verified facts yet._")
    lines.append("")

    # LEAD
    lines += ["## Research leads — chase before writing", ""]
    leads = grouped["LEAD"]
    if leads:
        for v in leads:
            lead = v.get("lead") or {}
            lines.append(f"- **{v['claim_text']}**")
            lines.append(f"  - Missing: {lead.get('missing', 'a reliable source')}")
            bc = lead.get("breadcrumb_source", {})
            if bc:
                lines.append(f"  - Breadcrumb: {bc.get('url', '')} ({bc.get('rsp_tier', '')})")
            for pc in lead.get("partial_corroboration", []):
                lines.append(f"  - Corroborates fact (not subject): {pc.get('url', '')} — "
                             f"\"{pc.get('quote', '')}\"")
            for q in lead.get("suggested_searches", []):
                lines.append(f"  - Try searching: `{q}`")
    else:
        lines.append("_No open leads._")
    lines.append("")

    # DEAD_END
    dead = grouped["DEAD_END"]
    if dead:
        lines += ["## UNVERIFIED — do not use", ""]
        for v in dead:
            lines.append(f"- {v['claim_text']} — {v.get('reasoning', 'no corroboration found')}")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_dossier.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add gapfinder/dossier.py tests/test_dossier.py
git commit -m "feat: dossier renderer (verified table / leads / unverified)"
```

---

### Task 8: CLI integration

**Files:**
- Modify: `gap_finder.py` (replace the `build_dossier` stub; add `--refresh-rsp` and `--search-backend`)
- Test: `tests/test_cli_integration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_integration.py`:

```python
import json
from pathlib import Path
import gap_finder
from gapfinder import worklist as worklist_mod
from tests.conftest import FIXTURES


def test_dossier_renders_when_verdicts_present(tmp_path, monkeypatch, capsys):
    # Arrange: a campaign whose output dir holds a verdicts file for the subject.
    camp = gap_finder.Campaign(name="test-camp")
    monkeypatch.setattr(camp, "output_dir", lambda: tmp_path)
    subj_dir = tmp_path / "Corina_Boettger"
    subj_dir.mkdir()
    (subj_dir / "vetting_verdicts.json").write_text((FIXTURES / "verdicts_sample.json").read_text())

    # Act
    gap_finder.build_dossier(camp, session=None, name="Corina Boettger")

    # Assert: dossier markdown written next to the verdicts.
    dossier_path = subj_dir / "dossier.md"
    assert dossier_path.exists()
    assert "## Verified facts" in dossier_path.read_text()


def test_dossier_emits_worklist_when_no_verdicts(tmp_path, monkeypatch):
    camp = gap_finder.Campaign(name="test-camp")
    monkeypatch.setattr(camp, "output_dir", lambda: tmp_path)

    # No verdicts yet; build_dossier should emit a worklist and return without error.
    # Coverage search is stubbed to avoid network.
    from gapfinder import search
    fake = search.FakeBackend({"corina": [search.SearchResult(url="https://nytimes.com/a", title="T", text="b")]})
    monkeypatch.setattr(gap_finder, "_dossier_backend", lambda args: fake, raising=False)

    gap_finder.build_dossier(camp, session=None, name="Corina Boettger",
                             backend=fake)
    wl = tmp_path / "Corina_Boettger" / "vetting_worklist.json"
    assert wl.exists()
    data = json.loads(wl.read_text())
    assert data["subject"]["name"] == "Corina Boettger"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m pytest tests/test_cli_integration.py -v`
Expected: FAIL — `build_dossier` currently calls `sys.exit(2)` / wrong signature.

- [ ] **Step 3: Implement `build_dossier` and helpers in `gap_finder.py`**

Add near the top of `gap_finder.py` (after imports):

```python
from gapfinder import worklist as worklist_mod
from gapfinder import verdicts as verdicts_mod
from gapfinder import dossier as dossier_mod
from gapfinder import search as search_mod
```

Add a helper for a filesystem-safe subject dir:

```python
def _subject_dir(campaign: "Campaign", name: str) -> Path:
    safe = name.replace(" ", "_").replace("/", "_")
    d = campaign.output_dir() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d
```

Replace the `build_dossier` stub with:

```python
def build_dossier(campaign: "Campaign", session, name: str, backend=None) -> None:
    """Stage 4. If verdicts exist, render the dossier. Otherwise gather coverage,
    build the worklist, and instruct the user to run the vetter subagent."""
    subj_dir = _subject_dir(campaign, name)
    verdicts_path = subj_dir / "vetting_verdicts.json"

    if verdicts_path.exists():
        data = verdicts_mod.load_verdicts(verdicts_path)
        md = dossier_mod.render_dossier(data, subject={"name": name})
        out = subj_dir / "dossier.md"
        out.write_text(md)
        log.info("wrote dossier -> %s", out)
        print(f"\nDossier written: {out}\n")
        return

    # No verdicts yet: build the worklist from coverage search.
    if backend is None:
        backend = search_mod.DDGBackend(session)
    hint = " ".join(campaign.search_hints)
    query = f"{name} {hint}".strip()
    log.info("dossier: no verdicts yet — gathering coverage for '%s'", name)
    coverage = search_mod.search_web(query, backend=backend)
    wl = worklist_mod.build_worklist(
        campaign=campaign.name,
        subject={"name": name},
        coverage=coverage,
        seed_claims=[],
    )
    path = worklist_mod.write_worklist(subj_dir, wl)
    log.info("wrote worklist -> %s", path)
    print(f"\nWorklist written: {path}")
    print("Next: run the source-vetter subagent (skills/vet-sources) over this worklist,")
    print(f"which writes {verdicts_path.name}. Then re-run --dossier to render.\n")
```

Wire the new flags into `build_arg_parser` (add before the `return p`):

```python
    p.add_argument("--refresh-rsp", action="store_true",
                   help="refresh the WP:RSP reliability cache before running")
    p.add_argument("--search-backend", choices=["ddg", "firecrawl"], default="ddg",
                   help="coverage-search backend for --dossier worklist building")
```

Update `main()`'s dossier branch:

```python
    if args.dossier:
        if args.refresh_rsp:
            from gapfinder import rsp as rsp_mod
            rsp_mod.refresh_from_wikipedia(session)
        backend = (search_mod.FirecrawlBackend() if args.search_backend == "firecrawl"
                   else search_mod.DDGBackend(session))
        build_dossier(campaign, session, args.dossier, backend=backend)
        return 0
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m pytest tests/test_cli_integration.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add gap_finder.py tests/test_cli_integration.py
git commit -m "feat: wire source vetter into --dossier (worklist out, verdicts -> dossier)"
```

---

### Task 9: The vetter subagent contract (the Claude layer)

**Files:**
- Create: `skills/vet-sources/SKILL.md`

This is the human/agent-facing contract, not Python. It defines exactly how the Claude subagent turns a worklist into verdicts.

- [ ] **Step 1: Write the SKILL.md**

Create `skills/vet-sources/SKILL.md`:

````markdown
---
name: vet-sources
description: Vet the sources in a vetting_worklist.json — classify reliability, chase breadcrumbs, and emit vetting_verdicts.json. Use when the gap finder has produced a worklist for a candidate and you need VERIFIED/LEAD/DEAD_END verdicts before building the dossier.
---

# Source Vetter

You are the reasoning half of Wikipedia Gap Finder's source vetter. You read one
`vetting_worklist.json` and write one `vetting_verdicts.json`. You do detective work and
verification only — **you never write article prose and you never assert a fact by
combining two sources yourself.**

## Input

A `vetting_worklist.json` (schema: `gapfinder/schemas/worklist.schema.json`) with the
subject, a list of sources (each pre-tagged with an `rsp_tier`), and optional seed claims.

## What to do, per claim

1. **Gather candidate claims:** use `seed_claims` plus any factual claims you extract from
   the sources' `fetched_text`.
2. **Try to VERIFY:** a claim is VERIFIED only if a **single reliable source**
   (`GENERALLY_RELIABLE`, or `MARGINAL` for non-contentious claims) both **names the
   subject** and **supports the claim**, and you can quote it verbatim.
3. **If only a breadcrumb exists** (an unreliable/user-generated source connects the
   subject to the fact, but no reliable source names the subject), **chase it**: run
   web searches (Firecrawl skill preferred; WebSearch otherwise) for a reliable source
   that names the subject *and* confirms the fact.
   - Caps: ≤5 searches and ≤3 page-reads per claim. When you hit a cap, stop and record
     `chase_log.capped = true`.
   - If the chase finds a qualifying single reliable source → **VERIFIED**.
   - If the fact is corroborated by a reliable source but the subject still isn't named
     there → **LEAD**. Record the breadcrumb, the partial corroboration, exactly what's
     missing, and 1–3 suggested searches.
   - If nothing corroborates → **DEAD_END**.

## The never-stitch rule (hard constraint)

You MUST NOT promote a claim to VERIFIED by combining a subject-naming unreliable source
with a fact-confirming reliable source. That is WP:SYNTH. Two half-sources = LEAD, always.

## BLP

If a claim is contentious (crime, health, sexuality, contested biography), it reaches
VERIFIED only with a `GENERALLY_RELIABLE` source. Otherwise it is DEAD_END — never hedged.

## Output

Write `vetting_verdicts.json` next to the worklist, matching
`gapfinder/schemas/verdicts.schema.json` exactly. Every VERIFIED entry needs at least one
`supporting` source with a non-empty verbatim `quote`. Emit JSON only — no prose.
````

- [ ] **Step 2: Sanity-check the SKILL.md references the real schema files**

Run: `ls gapfinder/schemas/worklist.schema.json gapfinder/schemas/verdicts.schema.json`
Expected: both paths exist.

- [ ] **Step 3: Commit**

```bash
git add skills/vet-sources/SKILL.md
git commit -m "docs: vet-sources subagent contract (classify + chase + never-stitch)"
```

---

### Task 10: End-to-end SYNTH-trap verification

**Files:**
- Test: `tests/test_end_to_end.py`

Proves the whole Python path (worklist → hand-authored verdicts fixture → dossier) keeps a SYNTH-trapped claim out of the facts table. No LLM in the loop — the fixture stands in for the subagent.

- [ ] **Step 1: Write the test**

Create `tests/test_end_to_end.py`:

```python
import json
from gapfinder import worklist, contract, verdicts, dossier, search
from tests.conftest import FIXTURES


def test_worklist_to_dossier_keeps_synth_claim_out_of_facts(tmp_path):
    # 1) Build a worklist from mixed-reliability coverage.
    coverage = [
        search.SearchResult(url="https://www.reuters.com/a", title="Reuters", text="…"),
        search.SearchResult(url="https://x.fandom.com/w", title="Fan wiki", text="won XYZ award"),
    ]
    wl = worklist.build_worklist("c", {"name": "Corina Boettger"}, coverage, [])
    contract.validate_worklist(wl)

    # 2) The subagent's verdicts (stand-in fixture) come back with a LEAD for the award.
    vdata = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    verdicts.load_verdicts(_write(tmp_path, vdata))  # validates

    # 3) Render the dossier and assert the SYNTH-trapped claim is a LEAD, not a fact.
    md = dossier.render_dossier(vdata, subject={"name": "Corina Boettger"})
    facts = md.split("## Research leads")[0]
    assert "Won XYZ award" not in facts
    assert "Won XYZ award" in md  # present as a lead
    assert "Voiced Paimon" in facts  # the genuinely-verified claim IS a fact


def _write(tmp_path, data):
    p = tmp_path / "vetting_verdicts.json"
    p.write_text(json.dumps(data))
    return p
```

- [ ] **Step 2: Run to verify it passes**

Run: `python3 -m pytest tests/test_end_to_end.py -v`
Expected: 1 passed.

- [ ] **Step 3: Run the full suite**

Run: `python3 -m pytest`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "test: end-to-end SYNTH-trap keeps unstitched claim out of facts table"
```

---

## Self-review

**Spec coverage:**
- Two-file boundary → Tasks 2, 5, 6, 8 ✓
- Three buckets (VERIFIED/LEAD/DEAD_END) → schema (Task 2), renderer (Task 7), e2e (Task 10) ✓
- Never-stitch / WP:SYNTH → SKILL.md (Task 9) + e2e proof (Task 10) ✓
- BLP handling → renderer banner (Task 7), SKILL.md rule (Task 9) ✓
- RSP tiering keyless + cache → Task 3 ✓
- Firecrawl default chase (subagent) + DDG fallback (Python coverage) → Task 4 backends + Task 9 chase + reconciliation note ✓
- Chase caps logged → SKILL.md (Task 9) ✓
- Pipeline integration (triage worklist / dossier merge) → Task 8 (dossier). *Triage (Stage 3) wiring is deferred: `--dossier` builds the worklist on demand, which covers the vetter end-to-end; folding it into `--triage` is a follow-up once Stage 3 exists.*

**Placeholder scan:** none — every step has runnable code/commands.

**Type consistency:** `search_web(query, backend, limit)`, `SearchResult(url,title,text)`, `build_worklist(campaign, subject, coverage, seed_claims)`, `load_verdicts(path)`, `by_bucket(data)`, `render_dossier(verdicts_data, subject)`, `build_dossier(campaign, session, name, backend=None)` — consistent across Tasks 4–8 and tests.

**Note on scope:** Stage 3 (triage) is not built here; this plan delivers the vetter as reachable through `--dossier`. That is a deliberate, working slice — flagged above, not a gap.
