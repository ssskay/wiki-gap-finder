"""Load and group the subagent's vetting_verdicts.json."""
from __future__ import annotations

import json
from pathlib import Path

from gapfinder import contract

BUCKETS = ("VERIFIED", "LEAD", "DEAD_END")


def load_verdicts(path) -> dict:
    """Load + schema-validate a verdicts file. Raises ValidationError if bad."""
    data = json.loads(Path(path).read_text())
    contract.validate_verdicts(data)
    return data


def by_bucket(verdicts_data: dict) -> dict[str, list[dict]]:
    """Group verdicts by bucket, always returning all three keys."""
    grouped: dict[str, list[dict]] = {b: [] for b in BUCKETS}
    for v in verdicts_data.get("verdicts", []):
        grouped.setdefault(v["bucket"], []).append(v)
    return grouped
