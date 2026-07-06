#!/usr/bin/env python3
"""
Wikipedia Gap Finder v2 — CLI
=============================

A campaign-driven pipeline that finds people from an underrepresented group who
should have an English Wikipedia article but don't, verifies every fact against
real sources, and hands the writer a research dossier.

HARD PRODUCT CONSTRAINT: this tool never writes article prose. English
Wikipedia banned LLM-generated/-rewritten article text (RfC March 2026). The
tool does detective work, verification, and structure only. A human writes every
sentence. See the MVP spec for the full rationale.

This module currently implements:
    Stage 1  Intake        (CSV/txt name lists + optional Wikidata SPARQL)
    Stage 2  Gap check     (enwiki search + redirects + Draft: + deletion log
                            + Wikidata sitelinks)

Stages 3 (notability triage) and 4 (dossier build) are scaffolded but not yet
implemented — build them after reviewing gap-check output.

Conventions: zero API keys, python3 + --break-system-packages, no venvs,
polite User-Agent, >=1s between requests with exponential backoff, thorough
logging.

Packaging: the console entry point `gap-finder` calls main(). The core install
is intentionally light (stdlib + requests + PyYAML). Rich is an optional [ui]
extra used only to prettify the gap-check table, and Firecrawl is an optional
[chase] extra for the coverage backend — both degrade gracefully when absent.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests'. Install: pip3 install requests --break-system-packages")

try:
    import yaml
except ImportError:
    sys.exit("Missing dependency 'PyYAML'. Install: pip3 install PyYAML --break-system-packages")

from gapfinder import worklist as worklist_mod
from gapfinder import verdicts as verdicts_mod
from gapfinder import dossier as dossier_mod
from gapfinder import search as search_mod

# Rich is an optional [ui] extra. When it's installed we render a prettier
# gap-check table; otherwise we fall back to the plain-text renderer below.
try:
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable
    _HAS_RICH = True
except ImportError:
    _RichConsole = None  # type: ignore[assignment,misc]
    _RichTable = None  # type: ignore[assignment,misc]
    _HAS_RICH = False


# --------------------------------------------------------------------------- #
# Constants & configuration
# --------------------------------------------------------------------------- #

# API etiquette: a descriptive User-Agent with contact info. Requests without
# one get throttled or blocked. See https://meta.wikimedia.org/wiki/User-Agent_policy
USER_AGENT = (
    "WikipediaGapFinder/2.0 (campaign research tool; contact sara@sarakay.me) "
    "python-requests/{}".format(requests.__version__)
)

ENWIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"

MIN_REQUEST_INTERVAL = 1.0   # seconds between external requests (rate-limit floor)
MAX_RETRIES = 4              # per-request retry attempts
BACKOFF_BASE = 2.0          # exponential backoff base (seconds)

DRAFT_NAMESPACE = 118        # enwiki Draft: namespace id

log = logging.getLogger("gap_finder")


# --------------------------------------------------------------------------- #
# Gap-check verdict vocabulary
# --------------------------------------------------------------------------- #

STATUS_GAP = "GAP"                            # no article, no draft — a real target
STATUS_EXISTS = "EXISTS"                      # article already exists
STATUS_REDIRECT_ONLY = "REDIRECT_ONLY"        # title redirects elsewhere (e.g. to a spouse/org)
STATUS_DRAFT_EXISTS = "DRAFT_EXISTS"          # someone is already drafting them
STATUS_DELETED_BEFORE = "DELETED_BEFORE"      # a prior article was deleted — red flag
STATUS_TRANSLATE_CANDIDATE = "TRANSLATE_CANDIDATE"  # exists in another language ⭐

# Priority when several signals fire at once. Lower index = reported as the
# primary status. EXISTS wins (nothing to do); TRANSLATE_CANDIDATE is the
# highest-value *actionable* state so it outranks a bare GAP.
STATUS_PRIORITY = [
    STATUS_EXISTS,
    STATUS_REDIRECT_ONLY,
    STATUS_DRAFT_EXISTS,
    STATUS_TRANSLATE_CANDIDATE,
    STATUS_DELETED_BEFORE,
    STATUS_GAP,
]


# --------------------------------------------------------------------------- #
# HTTP session with rate limiting + backoff (single choke point for all calls)
# --------------------------------------------------------------------------- #

class PoliteSession:
    """Wraps requests.Session with a global rate-limit floor and retry/backoff.

    Every external HTTP call in this tool goes through .get_json(), so rate
    limiting and etiquette are enforced in exactly one place.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < MIN_REQUEST_INTERVAL:
            wait = MIN_REQUEST_INTERVAL - elapsed
            log.debug("throttle: sleeping %.2fs", wait)
            time.sleep(wait)

    def get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET a JSON endpoint with rate limiting and exponential backoff."""
        last_err: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                log.debug("GET %s params=%s (attempt %d)", url, params, attempt)
                resp = self._session.get(url, params=params, timeout=30)
                self._last_request_ts = time.monotonic()
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_err = exc
                self._last_request_ts = time.monotonic()
                backoff = BACKOFF_BASE ** attempt
                log.warning("request failed (%s); backoff %.1fs then retry %d/%d",
                            exc, backoff, attempt, MAX_RETRIES)
                time.sleep(backoff)
        raise RuntimeError(f"request to {url} failed after {MAX_RETRIES} attempts: {last_err}")

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


# --------------------------------------------------------------------------- #
# Campaign config
# --------------------------------------------------------------------------- #

@dataclass
class Campaign:
    name: str
    description: str = ""
    name_lists: list[str] = field(default_factory=list)
    sparql: str | None = None
    search_hints: list[str] = field(default_factory=list)
    _source_path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Campaign":
        p = Path(path)
        if not p.exists():
            sys.exit(f"Campaign file not found: {p}")
        data = yaml.safe_load(p.read_text()) or {}
        intake = data.get("intake", {}) or {}
        camp = cls(
            name=data.get("name") or p.stem,
            description=data.get("description", ""),
            name_lists=list(intake.get("name_lists", []) or []),
            sparql=(intake.get("sparql") or None),
            search_hints=list(data.get("search_hints", []) or []),
            _source_path=p,
        )
        log.info("loaded campaign '%s': %s", camp.name, camp.description)
        return camp

    def output_dir(self) -> Path:
        d = Path("output") / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def resolve_path(self, rel: str) -> Path:
        """Resolve a path from the campaign file relative to CWD (spec uses
        project-root-relative paths like input/candidates.csv)."""
        return Path(rel)


# --------------------------------------------------------------------------- #
# Stage 1 — Intake
# --------------------------------------------------------------------------- #

def read_name_list(path: Path) -> list[str]:
    """Read names from a .csv or .txt file.

    CSV: takes the 'name' column if present, else the first column.
    TXT: one name per line. Blank lines and '#' comments are ignored.
    """
    names: list[str] = []
    if not path.exists():
        log.warning("name list not found: %s", path)
        return names

    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            sample = fh.read(2048)
            fh.seek(0)
            has_header = csv.Sniffer().has_header(sample) if sample.strip() else False
            if has_header:
                reader = csv.DictReader(fh)
                # pick the 'name' column, case-insensitive, else first field
                name_key = None
                for fn in reader.fieldnames or []:
                    if fn and fn.strip().lower() == "name":
                        name_key = fn
                        break
                if name_key is None and reader.fieldnames:
                    name_key = reader.fieldnames[0]
                for row in reader:
                    val = (row.get(name_key) or "").strip()
                    if val:
                        names.append(val)
            else:
                fh.seek(0)
                for row in csv.reader(fh):
                    if row and row[0].strip():
                        names.append(row[0].strip())
    else:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.append(line)

    log.info("intake: read %d names from %s", len(names), path)
    return names


def run_sparql(session: PoliteSession, query_body: str) -> list[str]:
    """Run a Wikidata SPARQL query and return person labels.

    The campaign `sparql` field holds the WHERE-clause body (per the spec's
    example). We wrap it into a complete SELECT that binds ?person and
    ?personLabel, so campaigns only supply the demographic-specific filters.
    """
    query = (
        "SELECT DISTINCT ?person ?personLabel WHERE {\n"
        f"{query_body}\n"
        '  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }\n'
        "} LIMIT 500"
    )
    log.info("intake: running Wikidata SPARQL query")
    data = session.get_json(WIKIDATA_SPARQL, {"query": query, "format": "json"})
    names: list[str] = []
    for binding in data.get("results", {}).get("bindings", []):
        label = binding.get("personLabel", {}).get("value")
        # Skip un-labelled items (label falls back to the Q-id)
        if label and not label.startswith("Q"):
            names.append(label)
    log.info("intake: SPARQL returned %d labelled people", len(names))
    return names


def collect_intake(campaign: Campaign, session: PoliteSession,
                   use_sparql: bool = True, limit: int | None = None) -> list[str]:
    """Stage 1: gather candidate names from all configured sources, de-duped.

    use_sparql=False skips the (potentially large) Wikidata redlist query, e.g.
    for a quick test on just the CSV names. limit caps the number of candidates.
    """
    seen: dict[str, None] = {}  # ordered de-dup, case-insensitive key
    order: list[str] = []

    def add(name: str) -> None:
        key = name.strip().lower()
        if key and key not in seen:
            seen[key] = None
            order.append(name.strip())

    for rel in campaign.name_lists:
        for n in read_name_list(campaign.resolve_path(rel)):
            add(n)

    if campaign.sparql and use_sparql:
        try:
            for n in run_sparql(session, campaign.sparql):
                add(n)
        except Exception as exc:  # SPARQL is optional; don't kill the run
            log.error("SPARQL intake failed (continuing without it): %s", exc)
    elif campaign.sparql and not use_sparql:
        log.info("intake: SPARQL query present but skipped (--no-sparql)")

    if limit is not None and len(order) > limit:
        log.info("intake: capping %d candidates to --limit %d", len(order), limit)
        order = order[:limit]

    log.info("intake: %d unique candidate names collected", len(order))
    return order


# --------------------------------------------------------------------------- #
# Stage 2 — Gap check
# --------------------------------------------------------------------------- #

@dataclass
class GapResult:
    name: str
    status: str
    # supporting signals (all optional, filled as discovered)
    exact_title: str | None = None
    is_redirect: bool = False
    redirect_target: str | None = None
    draft_title: str | None = None
    deletion_events: int = 0
    wikidata_id: str | None = None
    enwiki_sitelink: str | None = None
    other_wikis: list[str] = field(default_factory=list)
    search_hits: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _query_titles(session: PoliteSession, titles: list[str], redirects: bool) -> dict[str, Any]:
    params = {
        "action": "query",
        "format": "json",
        "prop": "info",
        "titles": "|".join(titles),
        "formatversion": "2",
    }
    if redirects:
        params["redirects"] = "1"
    return session.get_json(ENWIKI_API, params)


def check_exact_title(session: PoliteSession, name: str) -> dict[str, Any]:
    """Check whether an enwiki page with this exact title exists, and whether it
    is a redirect (and to where). Returns a small dict of findings."""
    findings: dict[str, Any] = {
        "exists": False,
        "is_redirect": False,
        "redirect_target": None,
        "title": None,
    }

    # First, don't auto-resolve redirects so we can detect redirect-only pages.
    data = _query_titles(session, [name], redirects=False)
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return findings
    page = pages[0]
    if page.get("missing"):
        return findings

    findings["exists"] = True
    findings["title"] = page.get("title")
    if page.get("redirect"):
        findings["is_redirect"] = True
        # Resolve the redirect target with a second call.
        resolved = _query_titles(session, [name], redirects=True)
        rd = resolved.get("query", {}).get("redirects", [])
        if rd:
            findings["redirect_target"] = rd[-1].get("to")
    return findings


def check_draft(session: PoliteSession, name: str) -> str | None:
    """Return the Draft: title if a draft exists, else None."""
    draft_title = f"Draft:{name}"
    data = _query_titles(session, [draft_title], redirects=False)
    pages = data.get("query", {}).get("pages", [])
    if pages and not pages[0].get("missing"):
        return pages[0].get("title")
    return None


def check_deletion_log(session: PoliteSession, name: str) -> int:
    """Count deletion-log events for this title (a prior deleted article is a
    red flag worth knowing before investing hours)."""
    params = {
        "action": "query",
        "format": "json",
        "list": "logevents",
        "leaction": "delete/delete",
        "letitle": name,
        "lelimit": "10",
        "formatversion": "2",
    }
    data = session.get_json(ENWIKI_API, params)
    events = data.get("query", {}).get("logevents", [])
    return len(events)


def search_enwiki(session: PoliteSession, name: str, limit: int = 5) -> list[str]:
    """Full-text-ish title search on enwiki (fuzzy safety net for near-misses)."""
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": name,
        "srlimit": str(limit),
        "srprop": "",
        "formatversion": "2",
    }
    data = session.get_json(ENWIKI_API, params)
    return [hit.get("title") for hit in data.get("query", {}).get("search", [])]


def check_wikidata(session: PoliteSession, name: str) -> dict[str, Any]:
    """Look the person up on Wikidata and inspect sitelinks.

    Returns wikidata_id, whether an enwiki sitelink exists, and the list of
    other-language wikipedia sitelinks (the translation-candidate signal).
    """
    findings: dict[str, Any] = {
        "wikidata_id": None,
        "enwiki_sitelink": None,
        "other_wikis": [],
    }

    # 1) search for the entity
    search = session.get_json(WIKIDATA_API, {
        "action": "wbsearchentities",
        "format": "json",
        "language": "en",
        "type": "item",
        "limit": "1",
        "search": name,
    })
    hits = search.get("search", [])
    if not hits:
        return findings
    qid = hits[0].get("id")
    findings["wikidata_id"] = qid

    # 2) fetch sitelinks for that entity
    ent = session.get_json(WIKIDATA_API, {
        "action": "wbgetentities",
        "format": "json",
        "ids": qid,
        "props": "sitelinks",
    })
    entity = ent.get("entities", {}).get(qid, {})
    sitelinks = entity.get("sitelinks", {}) or {}
    for site, info in sitelinks.items():
        if not site.endswith("wiki"):
            continue  # skip commons/wikinews/etc — we care about wikipedias
        if site in ("commonswiki", "specieswiki", "metawiki", "sourceswiki"):
            continue
        if site == "enwiki":
            findings["enwiki_sitelink"] = info.get("title")
        else:
            lang = site[:-4]  # 'frwiki' -> 'fr'
            findings["other_wikis"].append(lang)
    findings["other_wikis"].sort()
    return findings


def determine_status(r: GapResult) -> str:
    """Fold the collected signals into a single primary status using
    STATUS_PRIORITY. Multiple signals may apply; we surface the most important."""
    candidates: list[str] = []

    if r.exact_title and not r.is_redirect:
        candidates.append(STATUS_EXISTS)
    if r.enwiki_sitelink:
        candidates.append(STATUS_EXISTS)
    if r.is_redirect:
        candidates.append(STATUS_REDIRECT_ONLY)
    if r.draft_title:
        candidates.append(STATUS_DRAFT_EXISTS)
    if r.other_wikis and not r.enwiki_sitelink and not (r.exact_title and not r.is_redirect):
        candidates.append(STATUS_TRANSLATE_CANDIDATE)
    if r.deletion_events > 0:
        candidates.append(STATUS_DELETED_BEFORE)

    if not candidates:
        return STATUS_GAP

    for status in STATUS_PRIORITY:
        if status in candidates:
            return status
    return STATUS_GAP


def check_gap(session: PoliteSession, name: str) -> GapResult:
    """Stage 2 for one name: run every gap-check probe and produce a verdict."""
    log.debug("gap-check: '%s'", name)
    r = GapResult(name=name, status=STATUS_GAP)

    # exact title + redirect
    exact = check_exact_title(session, name)
    r.exact_title = exact["title"]
    r.is_redirect = exact["is_redirect"]
    r.redirect_target = exact["redirect_target"]

    # draft namespace
    r.draft_title = check_draft(session, name)

    # deletion log
    r.deletion_events = check_deletion_log(session, name)

    # wikidata sitelinks (translation signal)
    wd = check_wikidata(session, name)
    r.wikidata_id = wd["wikidata_id"]
    r.enwiki_sitelink = wd["enwiki_sitelink"]
    r.other_wikis = wd["other_wikis"]

    # fuzzy search safety net (only bother if we haven't confirmed an article)
    if not (r.exact_title and not r.is_redirect) and not r.enwiki_sitelink:
        r.search_hits = search_enwiki(session, name)

    r.status = determine_status(r)

    # human-readable notes
    if r.status == STATUS_REDIRECT_ONLY and r.redirect_target:
        r.notes.append(f"redirects to '{r.redirect_target}' — counts as a gap")
    if r.status == STATUS_TRANSLATE_CANDIDATE:
        r.notes.append(
            f"⭐ exists in {len(r.other_wikis)} other language(s): "
            f"{', '.join(r.other_wikis)} — translation-eligible (highest value)"
        )
    if r.deletion_events > 0:
        r.notes.append(
            f"⚠ {r.deletion_events} prior deletion-log event(s) — check AfD history "
            "before investing time"
        )
    if r.draft_title:
        r.notes.append(f"draft already exists: {r.draft_title} — someone may be working on them")

    log.info("gap-check: %-28s -> %s%s", name, r.status,
             (" | " + "; ".join(r.notes)) if r.notes else "")
    return r


def run_gap_check(campaign: Campaign, session: PoliteSession, names: list[str]) -> list[GapResult]:
    log.info("=== Stage 2: gap check (%d names) ===", len(names))
    results = [check_gap(session, n) for n in names]

    # summary counts
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    log.info("gap-check complete. Summary: %s",
             ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return results


# --------------------------------------------------------------------------- #
# State persistence (resumable runs)
# --------------------------------------------------------------------------- #

def save_gap_state(campaign: Campaign, results: list[GapResult]) -> Path:
    out = campaign.output_dir() / "gap_check.json"
    payload = {
        "campaign": campaign.name,
        "count": len(results),
        "results": [r.to_dict() for r in results],
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    log.info("wrote gap-check state -> %s", out)
    return out


ICON = {
    STATUS_GAP: "🟢",
    STATUS_TRANSLATE_CANDIDATE: "⭐",
    STATUS_EXISTS: "⚪",
    STATUS_REDIRECT_ONLY: "🔁",
    STATUS_DRAFT_EXISTS: "✍️",
    STATUS_DELETED_BEFORE: "⚠️",
}


def _row_detail(r: GapResult) -> str:
    """Detail cell shared by both the Rich and plain-text renderers."""
    detail = ""
    if r.status == STATUS_TRANSLATE_CANDIDATE:
        detail = f"{r.wikidata_id or '?'} · other langs: {', '.join(r.other_wikis)}"
    elif r.status == STATUS_REDIRECT_ONLY:
        detail = f"→ {r.redirect_target}"
    elif r.status == STATUS_EXISTS:
        detail = r.exact_title or r.enwiki_sitelink or ""
    elif r.status == STATUS_DRAFT_EXISTS:
        detail = r.draft_title or ""
    elif r.status == STATUS_GAP:
        detail = f"wikidata: {r.wikidata_id or 'none'}"
    if r.deletion_events > 0 and r.status != STATUS_DELETED_BEFORE:
        detail += f"  (⚠ {r.deletion_events} prior deletion)"
    return detail


def _status_counts(results: list[GapResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def _print_gap_table_rich(results: list[GapResult]) -> None:
    """Rich-powered table (only reached when the [ui] extra is installed)."""
    console = _RichConsole()  # type: ignore[misc]
    table = _RichTable(title="Gap-check results", show_lines=False)  # type: ignore[misc]
    table.add_column("", width=2)
    table.add_column("NAME", style="bold", no_wrap=True)
    table.add_column("STATUS")
    table.add_column("DETAIL", overflow="fold")
    for r in results:
        table.add_row(ICON.get(r.status, "  "), r.name, r.status, _row_detail(r))
    console.print(table)
    counts = _status_counts(results)
    console.print("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


def _print_gap_table_plain(results: list[GapResult]) -> None:
    """Plain-text table — the stdlib-only fallback when Rich isn't installed."""
    print()
    print(f"{'':2} {'NAME':30} {'STATUS':20} DETAIL")
    print("-" * 92)
    for r in results:
        print(f"{ICON.get(r.status, '  '):2} {r.name[:30]:30} {r.status:20} {_row_detail(r)}")
    print("-" * 92)
    counts = _status_counts(results)
    print("  ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print()


def print_gap_table(results: list[GapResult]) -> None:
    """Terminal table of gap-check results. Uses Rich when the [ui] extra is
    installed, otherwise falls back to a plain stdlib renderer."""
    if _HAS_RICH:
        _print_gap_table_rich(results)
    else:
        _print_gap_table_plain(results)


# --------------------------------------------------------------------------- #
# Stage 3 & 4 — not yet implemented (scaffolding)
# --------------------------------------------------------------------------- #

def run_triage(campaign: Campaign, session: PoliteSession) -> None:
    log.error("Stage 3 (notability triage) is not implemented yet. "
              "Review gap-check output first, then build this stage.")
    sys.exit(2)


def _subject_dir(campaign: "Campaign", name: str) -> Path:
    safe = name.replace(" ", "_").replace("/", "_")
    d = campaign.output_dir() / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


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
    if not coverage:
        log.warning("coverage search returned 0 sources for '%s' — worklist will be "
                    "empty. If using --search-backend firecrawl, confirm the 'firecrawl' "
                    "CLI is installed and on PATH.", name)
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


def run_report(campaign: Campaign) -> None:
    """Summary table from saved state (works for whatever stages have run)."""
    state = campaign.output_dir() / "gap_check.json"
    if not state.exists():
        log.error("No saved state at %s — run --check first.", state)
        sys.exit(2)
    data = json.loads(state.read_text())
    results = [GapResult(**{k: v for k, v in r.items()}) for r in data["results"]]
    print_gap_table(results)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gap-finder",
        description="Wikipedia Gap Finder v2 — campaign-driven redlist pipeline "
                    "(never writes article prose).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--campaign", required=True, help="path to campaign YAML")
    stage = p.add_mutually_exclusive_group(required=True)
    stage.add_argument("--check", action="store_true", help="Stages 1-2: intake + gap check")
    stage.add_argument("--triage", action="store_true", help="Stage 3: notability triage (WIP)")
    stage.add_argument("--dossier", metavar="NAME", help="Stage 4: build dossier for one person")
    stage.add_argument("--report", action="store_true", help="print summary table from saved state")
    p.add_argument("--no-sparql", action="store_true",
                   help="skip the Wikidata SPARQL intake (use only CSV/txt name lists)")
    p.add_argument("--limit", type=int, metavar="N",
                   help="cap the number of candidate names processed (handy for testing)")
    p.add_argument("--refresh-rsp", action="store_true",
                   help="refresh the WP:RSP reliability cache before running")
    p.add_argument("--search-backend", choices=["ddg", "firecrawl"], default="ddg",
                   help="coverage-search backend for --dossier worklist building")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging (logs every request)")
    return p


def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.verbose)

    campaign = Campaign.load(args.campaign)
    session = PoliteSession()

    if args.check:
        names = collect_intake(campaign, session,
                               use_sparql=not args.no_sparql, limit=args.limit)
        if not names:
            log.error("No candidate names collected — check the campaign's name_lists / sparql.")
            return 1
        results = run_gap_check(campaign, session, names)
        save_gap_state(campaign, results)
        print_gap_table(results)
        return 0

    if args.report:
        run_report(campaign)
        return 0

    if args.triage:
        run_triage(campaign, session)
        return 0

    if args.dossier:
        if args.refresh_rsp:
            from gapfinder import rsp as rsp_mod
            rsp_mod.refresh_from_wikipedia(session)
        backend = (search_mod.FirecrawlBackend() if args.search_backend == "firecrawl"
                   else search_mod.DDGBackend(session))
        build_dossier(campaign, session, args.dossier, backend=backend)
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
