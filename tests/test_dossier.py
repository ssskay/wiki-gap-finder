import json
import pytest
from jsonschema.exceptions import ValidationError
from gapfinder import dossier, verdicts
from tests.conftest import FIXTURES


def _sample():
    return json.loads((FIXTURES / "verdicts_sample.json").read_text())


def test_newline_in_quote_cannot_break_out_of_facts_table():
    data = _sample()
    # A verbatim web quote with an embedded newline must not end the table row.
    data["verdicts"][0]["supporting"][0]["quote"] = "line one\nline two | with pipe"
    md = dossier.render_dossier(data, subject={"name": "Corina Boettger"})
    table_rows = [ln for ln in md.splitlines() if ln.startswith("| ")]
    # The verified fact stays on a single table row (no stray newline leaked it out).
    fact_rows = [r for r in table_rows if "Voiced Paimon" in r]
    assert len(fact_rows) == 1
    assert "line one line two" in fact_rows[0]
    assert "\\|" in fact_rows[0]  # pipe was escaped, not left to start a column


def test_render_rejects_malformed_verdicts():
    with pytest.raises(ValidationError):
        dossier.render_dossier({"campaign": "c"}, subject={"name": "N"})


def test_by_bucket_raises_on_unknown_bucket():
    with pytest.raises(ValueError):
        verdicts.by_bucket({"verdicts": [{"bucket": "MAYBE", "claim_text": "x"}]})


def test_verified_backed_only_by_unreliable_source_is_not_printed_as_fact():
    # Defense-in-depth: even if the subagent marks a claim VERIFIED but its only
    # supporting source is user-generated, it must NOT appear as a verified fact.
    data = _sample()
    data["verdicts"][0]["supporting"][0]["rsp_tier"] = "USER_GENERATED"
    md = dossier.render_dossier(data, subject={"name": "Corina Boettger"})
    facts = md.split("## Research leads")[0]
    # Not a fact row...
    assert "| Voiced Paimon |" not in facts
    # ...but surfaced loudly as a flagged claim, not silently dropped.
    assert "Flagged" in md
    assert "Voiced Paimon" in md


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
