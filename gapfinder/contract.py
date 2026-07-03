"""Load and validate the two JSON-contract files (worklist + verdicts)."""
import json
from pathlib import Path
from jsonschema import Draft7Validator

_SCHEMA_DIR = Path(__file__).parent / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((_SCHEMA_DIR / name).read_text())


_WORKLIST_VALIDATOR = Draft7Validator(_load_schema("worklist.schema.json"))
_VERDICTS_VALIDATOR = Draft7Validator(_load_schema("verdicts.schema.json"))


def validate_worklist(data: dict) -> None:
    """Raise jsonschema.ValidationError if the worklist is malformed."""
    _WORKLIST_VALIDATOR.validate(data)


def validate_verdicts(data: dict) -> None:
    """Raise jsonschema.ValidationError if the verdicts file is malformed.

    Structurally enforces: bucket is a known value, and VERIFIED requires at
    least one supporting source, each of which requires a non-empty quote.
    """
    _VERDICTS_VALIDATOR.validate(data)
