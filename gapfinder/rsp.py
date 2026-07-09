"""Reliability tiering against Wikipedia's perennial-sources list (WP:RSP).

Keyless. Uses a bundled curated seed (gapfinder/data/rsp_seed.json — shipped
inside the wheel) as the authoritative map for common domains; unknown domains
return UNRATED so the subagent judges them from first principles.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("gap_finder.rsp")

_SEED_PATH = Path(__file__).resolve().parent / "data" / "rsp_seed.json"

UNRATED = ("UNRATED", "")


def _load_map() -> dict[str, dict]:
    data: dict[str, dict] = {}
    if _SEED_PATH.exists():
        data.update(json.loads(_SEED_PATH.read_text()))
    else:
        log.warning("rsp: bundled seed missing at %s — every domain will tier as "
                    "UNRATED (broken install?)", _SEED_PATH)
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


