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

## Install

```bash
pip install wiki-gap-finder            # installs the `gap-finder` command
pip install "wiki-gap-finder[ui]"      # + Rich-rendered tables
pip install "wiki-gap-finder[chase]"   # + the Firecrawl coverage backend
```

Or clone this repo and run `python3 gap_finder.py ...` directly — same CLI
(`pip3 install requests PyYAML jsonschema --break-system-packages`).

## Usage

Commands read and write paths relative to the current directory, so run them
from your project root (campaign paths like `input/candidates.csv` resolve
from there, and results land in `output/<campaign>/`).

```bash
gap-finder --campaign campaigns/<campaign>.yaml --check       # stages 1–2
gap-finder --campaign campaigns/<campaign>.yaml --check --no-sparql --limit 5
gap-finder --campaign campaigns/<campaign>.yaml --report      # table from saved state
gap-finder --campaign campaigns/<campaign>.yaml --dossier "Name Here"
gap-finder --campaign ... --dossier "Name" --search-backend firecrawl
```

A campaign is one small YAML — swapping demographics is a new file, zero code
changes. Minimal example:

```yaml
name: my-campaign
description: Who this campaign is about
intake:
  name_lists:
    - "input/candidates.csv"   # CSV with a `name` column, or one name per line
  # optional: a Wikidata SPARQL WHERE-clause body for redlist intake
search_hints:                  # appended to coverage searches
  - "activist"
```

Other flags: `--refresh-rsp` re-fetches the WP:RSP reliability cache (stored
under `~/.cache/wiki-gap-finder/`), `-v` logs every request.

**Heads-up on the keyless search default:** DuckDuckGo increasingly serves a
bot challenge to non-browser clients. If coverage search comes back empty, the
tool now says so loudly — use `--search-backend firecrawl` (with the
`firecrawl` CLI installed) for dependable coverage gathering.

## Conventions

Zero API keys on the default path (MediaWiki + Wikidata + DuckDuckGo are keyless;
Firecrawl is opt-in). Polite `User-Agent`, ≥1s between requests with exponential
backoff.

```bash
python3 -m pytest      # 44 tests
```

## Layout

- `gap_finder.py` — back-compat shim; the CLI lives in `gapfinder/cli.py`
- `gapfinder/` — the package (cli, contract, rsp, search, worklist, verdicts, dossier)
- `gapfinder/data/rsp_seed.json` — curated WP:RSP reliability seed (ships in the wheel)
- `skills/vet-sources/SKILL.md` — the Claude subagent contract
- `campaigns/` — one YAML per campaign
- `docs/superpowers/` — design spec and implementation plan

MIT licensed.
