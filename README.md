# Wikipedia Gap Finder v2

A campaign-driven pipeline that finds people from an underrepresented group who
should have an English Wikipedia article but don't, checks every fact against real
sources, and hands a human a research dossier they write the article from.

> **The tool never writes article prose.** English Wikipedia banned
> LLM-generated/-rewritten article text (RfC, March 2026). This tool does detective
> work, verification, and structure only — a human writes every sentence. That isn't a
> limitation to route around; it's the product's integrity claim: *AI found her and
> checked the facts; a human wrote her story.*

## Pipeline

1. **Intake** — names from CSV/txt lists and/or an optional Wikidata SPARQL redlist query.
2. **Gap check** — per name: enwiki title + fuzzy search, redirect detection, `Draft:`
   namespace, deletion-log history, and Wikidata sitelinks. Verdicts:
   `GAP / EXISTS / REDIRECT_ONLY / DRAFT_EXISTS / DELETED_BEFORE / TRANSLATE_CANDIDATE`
   (⭐ candidates that already exist in another language are the highest-value, since
   translation is an allowed path).
3. **Notability triage** *(planned)* — coverage search scored against WP:GNG.
4. **Source vetting → dossier** — see below.

## Source vetter

The vetter is two processes across a two-file JSON boundary, so each side is testable
in isolation:

```
gap_finder.py --dossier  →  vetting_worklist.json  →  Claude vet-sources subagent
                                                            │
dossier.md  ←  gap_finder.py --dossier  ←  vetting_verdicts.json
```

- **Python** (keyless): gathers coverage, tiers each source against Wikipedia's
  perennial-sources list (WP:RSP), and renders the dossier.
- **The Claude subagent** (`skills/vet-sources`): classifies reliability and traces
  breadcrumbs, sorting every claim into one of three buckets:

  | Bucket | Meaning | Dossier section |
  |---|---|---|
  | **VERIFIED** | a single reliable source names the subject *and* supports the claim, with a verbatim quote | Verified facts table |
  | **LEAD** | a breadcrumb is real, but no reliable source names the subject yet | Research leads — chase before writing |
  | **DEAD_END** | no corroboration found | UNVERIFIED — do not use |

**The never-stitch rule (WP:SYNTH):** the vetter may not promote a LEAD to VERIFIED by
combining a subject-naming unreliable source with a fact-confirming reliable source. Two
half-sources stay a LEAD. And the renderer structurally refuses to print any fact backed
only by an unreliable source — even if a verdicts file claims otherwise.

## Usage

```bash
python3 gap_finder.py --campaign campaigns/<campaign>.yaml --check       # stages 1–2
python3 gap_finder.py --campaign campaigns/<campaign>.yaml --check --no-sparql --limit 5
python3 gap_finder.py --campaign campaigns/<campaign>.yaml --report      # table from saved state
python3 gap_finder.py --campaign campaigns/<campaign>.yaml --dossier "Name Here"
```

Swapping demographics is a new YAML in `campaigns/` — zero code changes. Results are
written under `output/<campaign>/` (JSON state + markdown), so runs are resumable.

## Conventions

Zero API keys on the default path (MediaWiki + Wikidata + DuckDuckGo are keyless;
Firecrawl is opt-in). `python3` + `--break-system-packages`, no venvs. Polite
`User-Agent`, ≥1s between requests with exponential backoff.

```bash
pip3 install requests PyYAML jsonschema --break-system-packages
python3 -m pytest      # 31 tests
```

## Layout

- `gap_finder.py` — CLI; intake + gap check (stages 1–2) and dossier wiring (stage 4)
- `gapfinder/` — the source-vetter package (contract, rsp, search, worklist, verdicts, dossier)
- `skills/vet-sources/SKILL.md` — the Claude subagent contract
- `campaigns/` — one YAML per campaign
- `docs/superpowers/` — design spec and implementation plan
