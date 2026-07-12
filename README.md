# Wikipedia Gap Finder v2

A campaign-driven pipeline that finds people from an underrepresented group who
should have an English Wikipedia article but don't, checks every fact against real
sources, and hands a human a research dossier they write the article from.

> **The tool never writes article prose.** English Wikipedia prohibits
> LLM-generated/-rewritten article content (guideline enacted by RfC, March 2026, with
> narrow copyedit and translation exceptions). This tool does detective work,
> verification, and structure only — a human writes every sentence, and the dossier is
> a map, not a source: the writer opens and reads every cited source themselves. That
> isn't a limitation to route around; it's the product's integrity claim: *AI found her
> and gathered the evidence; a human checked every source and wrote her story.*

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ssskay/wiki-gap-finder/main/docs/images/pipeline-dark.svg">
  <img alt="Four steps: start with names (orgs, books, event lists); find who's missing (no Wikipedia article yet); check every fact (real sources, exact quotes); a human writes every single sentence. The first three are the AI's detective work, the last is the human's." src="https://raw.githubusercontent.com/ssskay/wiki-gap-finder/main/docs/images/pipeline-light.svg">
</picture>

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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ssskay/wiki-gap-finder/main/docs/images/vetter-loop-dark.svg">
  <img alt="gap_finder --dossier gathers coverage and writes vetting_worklist.json; the Claude vet-sources subagent classifies and chases, writing vetting_verdicts.json (VERIFIED / LEAD / DEAD_END); gap_finder --dossier then renders dossier.md, which a human writes from. The JSON files are the whole contract." src="https://raw.githubusercontent.com/ssskay/wiki-gap-finder/main/docs/images/vetter-loop-light.svg">
</picture>

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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/ssskay/wiki-gap-finder/main/docs/images/never-stitch-dark.svg">
  <img alt="A fan wiki that names her plus a news story that proves the fact but not her is still not a fact — it stays a research lead. Only one reliable source that names her and states the fact becomes a verified fact, quoted in the dossier." src="https://raw.githubusercontent.com/ssskay/wiki-gap-finder/main/docs/images/never-stitch-light.svg">
</picture>

## Install

```bash
pip install wiki-gap-finder            # installs the `gap-finder` command
pip install "wiki-gap-finder[ui]"      # + Rich-rendered tables
pip install "wiki-gap-finder[chase]"   # + the Firecrawl coverage backend
```

Or clone this repo and run `python3 gap_finder.py ...` directly — same CLI
(`pip3 install requests PyYAML jsonschema --break-system-packages`).

## Install as a Claude skill

The source vetter ships as a standalone Claude skill (`vet-sources`) — the
reasoning half of the pipeline, packaged so Claude can classify sources and
emit verdicts on its own. Two ways to install it:

- **Download and drop into Claude.** Grab `vet-sources.skill` from the
  [latest release](https://github.com/ssskay/wiki-gap-finder/releases/latest)
  and drop the file into Claude (it's a zip with a top-level `vet-sources/`
  folder — SKILL.md plus the JSON schemas it references).
- **Clone into your skills directory.** Copy `skills/vet-sources/` into
  `~/.claude/skills/`:

  ```bash
  cp -r skills/vet-sources ~/.claude/skills/
  ```

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
changes. One rule for lists naming living people (the spirit of WP:BLPCAT): only
include identity attributes the person has publicly self-identified with, and only
when they're relevant to their public life. Minimal example:

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

Other flags: `-v` logs every request.

**Heads-up on the keyless search default:** DuckDuckGo increasingly serves a
bot challenge to non-browser clients. If coverage search comes back empty, the
tool now says so loudly — use `--search-backend firecrawl` (with the
`firecrawl` CLI installed) for dependable coverage gathering.

## Conventions

Zero API keys on the default path (MediaWiki + Wikidata + DuckDuckGo are keyless;
Firecrawl is opt-in). Polite `User-Agent`, ≥1s between requests with exponential
backoff, and `maxlag=5` on MediaWiki API calls so the tool yields when servers lag.

```bash
python3 -m pytest      # 54 tests
```

## Layout

- `gap_finder.py` — back-compat shim; the CLI lives in `gapfinder/cli.py`
- `gapfinder/` — the package (cli, contract, rsp, search, worklist, verdicts, dossier)
- `gapfinder/data/rsp_seed.json` — curated WP:RSP reliability seed (ships in the wheel)
- `skills/vet-sources/SKILL.md` — the Claude subagent contract
- `scripts/build_skill.sh` — packages the skill into `dist/vet-sources.skill`
- `campaigns/` — one YAML per campaign
- `docs/superpowers/` — design spec and implementation plan

## Releasing

Tag the version from `pyproject.toml`, cut a GitHub release, then build and
attach the skill asset:

```bash
git tag -a vX.Y.Z -m "wiki-gap-finder vX.Y.Z" && git push origin vX.Y.Z
gh release create vX.Y.Z --title vX.Y.Z --notes "..."
scripts/build_skill.sh                              # → dist/vet-sources.skill
gh release upload vX.Y.Z dist/vet-sources.skill
```

MIT licensed.
