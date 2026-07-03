import json
from gapfinder import worklist, contract, verdicts, dossier, search
from tests.conftest import FIXTURES


def test_worklist_to_dossier_keeps_synth_claim_out_of_facts(tmp_path):
    # 1) Build a worklist from mixed-reliability coverage.
    coverage = [
        search.SearchResult(url="https://www.reuters.com/a", title="Reuters", text="…"),
        search.SearchResult(url="https://x.fandom.com/w", title="Fan wiki", text="won XYZ award"),
    ]
    wl = worklist.build_worklist("c", {"name": "Corina Boettger"}, coverage, [])
    contract.validate_worklist(wl)

    # 2) The subagent's verdicts (stand-in fixture) come back with a LEAD for the award.
    vdata = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    verdicts.load_verdicts(_write(tmp_path, vdata))  # validates

    # 3) Render the dossier and assert the SYNTH-trapped claim is a LEAD, not a fact.
    md = dossier.render_dossier(vdata, subject={"name": "Corina Boettger"})
    facts = md.split("## Research leads")[0]
    assert "Won XYZ award" not in facts
    assert "Won XYZ award" in md  # present as a lead
    assert "Voiced Paimon" in facts  # the genuinely-verified claim IS a fact


def _write(tmp_path, data):
    p = tmp_path / "vetting_verdicts.json"
    p.write_text(json.dumps(data))
    return p
