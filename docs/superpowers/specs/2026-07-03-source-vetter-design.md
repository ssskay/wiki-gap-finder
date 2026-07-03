# Source Vetter — Design Spec

**Date:** 2026-07-03
**Component of:** Wikipedia Gap Finder v2
**Status:** Approved for planning

## 1. Motivation

The dossier's integrity claim is *"AI found her and checked the facts; a human wrote
her story."* The fact-checking half is currently hand-waved: Stage 3 (triage) counts
coverage and Stage 4 (dossier) assembles a `claim | source URL | quote` table, but
nothing rigorously decides **whether a given source can actually carry a given fact
onto English Wikipedia.**

Two real-world problems make this hard, and both come from the same insight (raised by
Sara):

1. **Reliability is not binary and not obvious from the URL.** A fan wiki, a press
   release, an interview, and a newspaper are all "sources," but Wikipedia treats them
   very differently (WP:RSP, WP:V, WP:BLP).

2. **The most useful lead is often in an *unreliable* source.** A fan wiki says *"He won
   the XYZ award for production Y."* The XYZ award for production Y is independently
   verifiable in a reliable source — **but that reliable source never names him.** The
   claim is therefore *not verified* (no reliable source connects subject → fact), yet
   the breadcrumb is gold: it tells you exactly what to go dig for.

The Source Vetter turns this judgment into a repeatable, auditable step.

### Hard product constraint (unchanged)

The vetter **never writes article prose** and **never asserts a fact by stitching two
sources together itself**. Combining "fan wiki says he won X" + "reliable source says X
happened" into "he won X" is exactly WP:SYNTH, which Wikipedia prohibits. The vetter's
job is to *classify* and *chase*, not to *conclude*.

## 2. Architecture — the two-file boundary

The vetter is **two processes communicating through two JSON files**. Neither side
reasons about the other's internals; each is testable in isolation.

```
gap_finder.py  --triage / --dossier
        │  • gather coverage sources (search_web)
        │  • fetch raw source text
        │  • keyless RSP domain-tiering
        ▼
  output/<campaign>/<name>/vetting_worklist.json      "sources + seed claims, out"
        │
        ▼
  Claude Source-Vetter subagent   (run via Claude Code)
        │  • extract/confirm candidate claims
        │  • classify sources (RSP tier + judgment)
        │  • chase breadcrumbs with search_web
        ▼
  output/<campaign>/<name>/vetting_verdicts.json      "buckets + quotes, in"
        │
        ▼
gap_finder.py  --dossier   merges verdicts into the facts table + research-leads section
```

**The contract is the two files.** Python never reasons; the subagent never touches the
dossier markdown. Swapping the subagent for an API-inline vetter later (the rejected
"standalone" option) changes nothing on the Python side.

### Rejected alternatives

- **Standalone (script calls the Anthropic API inline):** one-command dossiers, but
  breaks the zero-key default and couples fetching to a specific model API. Kept as a
  future drop-in behind the same JSON contract.
- **Pure heuristic (no LLM):** zero-key and fully standalone, but cannot handle
  paraphrase, aliases, or the SYNTH boundary — the whole point of the feature.

## 3. The three buckets

Every candidate claim lands in exactly one bucket. Buckets map onto dossier sections the
MVP spec already defines.

| Bucket | Definition | Dossier destination |
|---|---|---|
| **VERIFIED** | A **single reliable source** both names the subject *and* supports the claim, with a verbatim quote. | Verified-facts table: `claim \| source URL \| quote` |
| **LEAD** | Breadcrumb is real: an unreliable/marginal source connects subject→fact, and a reliable source corroborates the fact but **not** the subject. | New **"Research leads — chase before writing"** section, stating what's missing. |
| **DEAD_END** | No corroboration found anywhere after chasing. | Listed under the spec's existing `UNVERIFIED — do not use`, or dropped. |

### The never-stitch rule (WP:SYNTH guardrail)

A LEAD becomes VERIFIED **only** when a *single* reliable source makes the whole
connection (subject + fact) on its own. The vetter is explicitly forbidden from promoting
a LEAD by combining a subject-naming unreliable source with a fact-confirming reliable
source. This rule is hard-coded into the subagent's instructions and is the core
correctness property of the component.

### BLP handling

Most candidates are living people. Any claim flagged `contentious` (crime, health,
sexuality, contested biographical detail) requires a `GENERALLY_RELIABLE` source to reach
VERIFIED — MARGINAL/UNRATED is not enough. Contentious claims that fall short are dropped,
never hedged (WP:BLP).

## 4. Reliability tiering (keyless, in Python)

On first run, fetch Wikipedia's **perennial sources list** (WP:RSP) via the MediaWiki API
and cache to `data/rsp_cache.json` as `domain → {tier, note, source_name}`. Refresh on
demand (`--refresh-rsp`); otherwise use cache (zero network, offline-friendly).

Tiers:

- `GENERALLY_RELIABLE`
- `MARGINAL` (additional considerations / no consensus)
- `GENERALLY_UNRELIABLE`
- `DEPRECATED` (effectively banned)
- `USER_GENERATED` (wikis, fan wikis, forums, self-published — e.g. `fandom.com`)
- `UNRATED` — domain not on the RSP list; the subagent judges from first principles
  using WP:RS criteria (independence, editorial oversight, reputation).

Parsing the RSP table is best-effort; the `UNRATED` fallback absorbs any entries the
parser misses, so incomplete parsing degrades gracefully rather than failing.

## 5. Search backend (the chase)

Per the MVP spec, all web search sits behind **one swappable function**,
`search_web(query) -> list[SearchResult]`, where a `SearchResult` carries at least
`{url, title, text}` (`text` = full-page markdown when available — the vetter must be
able to *read* a page to find breadcrumbs).

- **Default backend: Firecrawl** (search + full-page markdown). Chosen because breadcrumb
  tracing needs page *content*, not just snippets.
- **Fallback backend: DuckDuckGo HTML scraping** — the zero-dependency path from the
  original spec, kept behind the same interface. Selectable via config/flag.

The backend is the only fragile, swappable part; isolating it keeps the rest stable.

## 6. Data contract

### 6.1 `vetting_worklist.json` (Python → subagent)

```json
{
  "campaign": "disability-pride-2026",
  "subject": {
    "name": "Corina Boettger",
    "aliases": ["Cori Boettger"],
    "wikidata_id": "Q...",
    "known_for_hint": "voice actor; disability advocate"
  },
  "sources": [
    {
      "source_id": "s1",
      "url": "https://example.com/article",
      "domain": "example.com",
      "title": "…",
      "rsp_tier": "GENERALLY_RELIABLE",
      "rsp_note": "…",
      "fetched_text": "full markdown or excerpt",
      "discovery": "coverage_search"
    }
  ],
  "seed_claims": [
    {
      "claim_id": "c1",
      "text": "Won the XYZ Award for production Y (2019)",
      "from_source_id": "s3",
      "claim_type": "award",
      "contentious": false
    }
  ]
}
```

`seed_claims` may be empty or drawn from structured places (Wikidata statements,
user-provided). The subagent may add its own discovered claims in the verdicts.

### 6.2 `vetting_verdicts.json` (subagent → Python)

```json
{
  "campaign": "disability-pride-2026",
  "subject_name": "Corina Boettger",
  "generated_by": "claude-source-vetter",
  "verdicts": [
    {
      "claim_id": "c1",
      "claim_text": "Won the XYZ Award for production Y (2019)",
      "bucket": "LEAD",
      "claim_type": "award",
      "contentious": false,
      "supporting": [],
      "lead": {
        "breadcrumb_source": {"url": "https://fandom…", "rsp_tier": "USER_GENERATED"},
        "partial_corroboration": [
          {"url": "https://reliable…", "quote": "The XYZ Award for 2019 went to production Y.",
           "note": "confirms the award exists but does not name the subject"}
        ],
        "missing": "a reliable source naming Corina Boettger in connection with the XYZ Award",
        "suggested_searches": ["\"Corina Boettger\" XYZ Award", "production Y cast XYZ Award"]
      },
      "reasoning": "No reliable source connects the subject to the award; SYNTH forbids stitching.",
      "chase_log": {"searches_run": 3, "pages_fetched": 2, "capped": false}
    },
    {
      "claim_id": "c2",
      "claim_text": "Voiced Paimon in Genshin Impact",
      "bucket": "VERIFIED",
      "claim_type": "role",
      "contentious": false,
      "supporting": [
        {"source_id": "s1", "url": "https://reliable…", "rsp_tier": "GENERALLY_RELIABLE",
         "quote": "Boettger voices Paimon in the English dub."}
      ],
      "lead": null,
      "reasoning": "Single reliable source names subject and supports claim.",
      "chase_log": {"searches_run": 0, "pages_fetched": 0, "capped": false}
    }
  ],
  "summary": {"verified": 1, "lead": 1, "dead_end": 0}
}
```

## 7. Chase guardrails

Sara's directive is "chase aggressively," bounded by safety caps so one stubborn claim
can't spiral. Defaults (configurable):

- `max_searches_per_claim`: 5
- `max_pages_fetched_per_claim`: 3
- `max_claims_per_subject`: 40

When a cap is hit, the verdict records `chase_log.capped = true` and the vetter stops
chasing that claim (records it as LEAD or DEAD_END with what it had). Caps are logged, never
silent — a capped run must be visibly capped.

## 8. Subagent contract (the "Claude layer")

Invoked via Claude Code (Agent tool / a `vet-sources` skill) against one
`vetting_worklist.json`. Its instructions encode:

1. For each source: assign/confirm reliability tier (use provided RSP tier; judge UNRATED
   from WP:RS criteria).
2. Extract candidate claims from source text; merge with `seed_claims`.
3. For each claim: attempt VERIFIED via a single reliable source. If only a breadcrumb
   exists, chase with `search_web` (within caps) for a reliable source that names the
   subject *and* confirms the fact.
4. Apply the **never-stitch rule** and **BLP** rule.
5. Emit `vetting_verdicts.json` matching the schema exactly. Every VERIFIED needs a
   verbatim quote from a reliable, subject-naming source.

The subagent returns raw JSON only — no prose, no dossier writing.

## 9. Pipeline integration

- **Stage 3 (triage):** the notability verdict (STRONG/BORDERLINE/SKIP) uses the vetter's
  count of VERIFIED claims backed by independent `GENERALLY_RELIABLE` sources, replacing
  the current naive source count. Triage produces the initial `vetting_worklist.json`.
- **Stage 4 (dossier):** `--dossier` reads `vetting_verdicts.json` and renders:
  - VERIFIED → verified-facts table (with quotes),
  - LEAD → "Research leads — chase before writing" section,
  - DEAD_END → `UNVERIFIED — do not use`.
  If no verdicts file exists yet, `--dossier` emits the worklist and instructs the user to
  run the vetter subagent first.

## 10. Testing strategy

- **Python, keyless, unit-testable:** RSP parse/cache; `search_web` interface with a
  fake backend; worklist assembly; verdicts→dossier rendering (golden-file test of a
  known verdicts JSON → expected markdown).
- **Contract tests:** JSON schema validation on both files; a hand-authored
  `vetting_verdicts.json` fixture drives dossier rendering with no LLM in the loop.
- **Subagent behavior:** fixture worklists exercising each bucket, especially the
  SYNTH trap (breadcrumb + fact-only-corroboration must yield LEAD, never VERIFIED) and a
  BLP contentious claim with only MARGINAL support (must not reach VERIFIED).

## 11. Out of scope (this component)

Prose generation (ever); auto-editing Wikipedia; Wikidata writes; deciding notability
policy beyond GNG counting; a UI. The vetter informs the dossier — Sara still writes every
sentence.
