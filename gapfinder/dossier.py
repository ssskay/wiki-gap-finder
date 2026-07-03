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
