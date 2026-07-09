"""Reliability tiering against Wikipedia's perennial-sources list (WP:RSP).

Keyless. Uses a bundled curated seed (gapfinder/data/rsp_seed.json — shipped
inside the wheel) as the authoritative map for common domains; unknown domains
return UNRATED so the subagent judges them from first principles.
refresh_from_wikipedia() is a best-effort augment cached under ~/.cache.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("gap_finder.rsp")

_SEED_PATH = Path(__file__).resolve().parent / "data" / "rsp_seed.json"
_CACHE_PATH = Path.home() / ".cache" / "wiki-gap-finder" / "rsp_cache.json"

UNRATED = ("UNRATED", "")


def _load_map() -> dict[str, dict]:
    data: dict[str, dict] = {}
    if _SEED_PATH.exists():
        data.update(json.loads(_SEED_PATH.read_text()))
    else:
        log.warning("rsp: bundled seed missing at %s — every domain will tier as "
                    "UNRATED (broken install?)", _SEED_PATH)
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
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
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
