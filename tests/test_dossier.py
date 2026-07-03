import json
from gapfinder import dossier, verdicts
from tests.conftest import FIXTURES


def _sample():
    return json.loads((FIXTURES / "verdicts_sample.json").read_text())


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
