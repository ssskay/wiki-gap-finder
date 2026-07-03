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
