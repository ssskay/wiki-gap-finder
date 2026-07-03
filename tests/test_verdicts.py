import json
import pytest
from jsonschema.exceptions import ValidationError
from gapfinder import verdicts
from tests.conftest import FIXTURES


def test_load_valid_verdicts(tmp_path):
    src = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    p = tmp_path / "vetting_verdicts.json"
    p.write_text(json.dumps(src))
    loaded = verdicts.load_verdicts(p)
    assert loaded["summary"]["verified"] == 1
    assert {v["bucket"] for v in loaded["verdicts"]} == {"VERIFIED", "LEAD"}


def test_load_rejects_invalid(tmp_path):
    bad = {"campaign": "c"}  # missing required fields
    p = tmp_path / "vetting_verdicts.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(ValidationError):
        verdicts.load_verdicts(p)


def test_by_bucket_groups_claims():
    src = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    grouped = verdicts.by_bucket(src)
    assert len(grouped["VERIFIED"]) == 1
    assert len(grouped["LEAD"]) == 1
    assert grouped["DEAD_END"] == []
