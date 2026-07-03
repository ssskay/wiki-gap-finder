import json
from pathlib import Path
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
