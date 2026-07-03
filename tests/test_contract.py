import json
import pytest
from jsonschema.exceptions import ValidationError
from gapfinder import contract
from tests.conftest import FIXTURES


def test_valid_worklist_passes():
    data = json.loads((FIXTURES / "worklist_sample.json").read_text())
    contract.validate_worklist(data)  # must not raise


def test_valid_verdicts_passes():
    data = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    contract.validate_verdicts(data)  # must not raise


def test_verified_without_quote_is_rejected():
    data = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    data["verdicts"][0]["supporting"] = []  # VERIFIED with no supporting source
    with pytest.raises(ValidationError):
        contract.validate_verdicts(data)


def test_unknown_bucket_is_rejected():
    data = json.loads((FIXTURES / "verdicts_sample.json").read_text())
    data["verdicts"][0]["bucket"] = "MAYBE"
    with pytest.raises(ValidationError):
        contract.validate_verdicts(data)
