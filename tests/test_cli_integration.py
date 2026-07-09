import json
from pathlib import Path

import pytest

import gap_finder
from gapfinder import worklist as worklist_mod
from tests.conftest import FIXTURES


def test_dossier_renders_when_verdicts_present(tmp_path, monkeypatch, capsys):
    # Arrange: a campaign whose output dir holds a verdicts file for the subject.
    camp = gap_finder.Campaign(name="test-camp")
    monkeypatch.setattr(camp, "output_dir", lambda: tmp_path)
    subj_dir = tmp_path / "Corina_Boettger"
    subj_dir.mkdir()
    (subj_dir / "vetting_verdicts.json").write_text((FIXTURES / "verdicts_sample.json").read_text())

    # Act
    gap_finder.build_dossier(camp, session=None, name="Corina Boettger")

    # Assert: dossier markdown written next to the verdicts.
    dossier_path = subj_dir / "dossier.md"
    assert dossier_path.exists()
    assert "## Verified facts" in dossier_path.read_text()


def test_dossier_emits_worklist_when_no_verdicts(tmp_path, monkeypatch):
    camp = gap_finder.Campaign(name="test-camp")
    monkeypatch.setattr(camp, "output_dir", lambda: tmp_path)

    # No verdicts yet; build_dossier should emit a worklist and return without error.
    # Coverage search is stubbed to avoid network.
    from gapfinder import search
    fake = search.FakeBackend({"corina": [search.SearchResult(url="https://nytimes.com/a", title="T", text="b")]})

    gap_finder.build_dossier(camp, session=None, name="Corina Boettger", backend=fake)
    wl = tmp_path / "Corina_Boettger" / "vetting_worklist.json"
    assert wl.exists()
    data = json.loads(wl.read_text())
    assert data["subject"]["name"] == "Corina Boettger"


def test_headerless_single_column_csv_keeps_first_name(tmp_path):
    # The most obvious input a stranger will try: a bare list of names. The CSV
    # sniffer used to misread the first name as a header row and drop it.
    p = tmp_path / "names.csv"
    p.write_text("Ada Lovelace\nGrace Hopper\n")
    assert gap_finder.read_name_list(p) == ["Ada Lovelace", "Grace Hopper"]


def test_csv_with_name_header_still_skips_the_header(tmp_path):
    p = tmp_path / "names.csv"
    p.write_text("name,source\nAda Lovelace,seed\n")
    assert gap_finder.read_name_list(p) == ["Ada Lovelace"]


def test_malformed_campaign_yaml_exits_with_message(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed\nintake: {")
    with pytest.raises(SystemExit) as excinfo:
        gap_finder.Campaign.load(bad)
    assert "campaign" in str(excinfo.value).lower()


def test_wrong_shape_campaign_yaml_exits_with_message(tmp_path):
    bad = tmp_path / "list.yaml"
    bad.write_text("- not\n- a\n- mapping\n")
    with pytest.raises(SystemExit) as excinfo:
        gap_finder.Campaign.load(bad)
    assert "campaign" in str(excinfo.value).lower()


def test_network_failure_is_a_friendly_error_not_a_traceback(tmp_path, monkeypatch):
    camp_yaml = tmp_path / "c.yaml"
    camp_yaml.write_text("name: t\n")
    from gapfinder import cli
    def boom(*a, **k):
        raise RuntimeError("GET failed after 4 attempts: HTTP 500")
    monkeypatch.setattr(cli, "collect_intake", boom)
    rc = cli.main(["--campaign", str(camp_yaml), "--check", "--no-sparql"])
    assert rc == 1  # clean exit code, no exception propagated


def test_refresh_rsp_flag_is_gone(tmp_path):
    # --refresh-rsp was a documented no-op (the wikitext parser was a stub);
    # it was removed rather than shipped as a stub. argparse must reject it.
    camp_yaml = tmp_path / "c.yaml"
    camp_yaml.write_text("name: t\n")
    from gapfinder import cli, rsp
    assert not hasattr(rsp, "refresh_from_wikipedia")
    with pytest.raises(SystemExit):
        cli.main(["--campaign", str(camp_yaml), "--report", "--refresh-rsp"])
