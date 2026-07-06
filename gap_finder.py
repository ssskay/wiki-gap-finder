#!/usr/bin/env python3
"""
Backwards-compatible shim.
==========================

The CLI now lives in ``gapfinder.cli`` and is exposed as the ``gap-finder``
console script (see pyproject.toml). This module is kept so that the historical
entry points keep working unchanged:

    python3 gap_finder.py --campaign ... --check     # run as a script
    import gap_finder; gap_finder.Campaign(...)      # import the old symbols

Everything is re-exported from ``gapfinder.cli`` — there is no logic here.
"""

from __future__ import annotations

from gapfinder.cli import *  # noqa: F401,F403  (re-export public API)
from gapfinder.cli import main  # noqa: F401  (explicit: not caught by star import if __all__ is set)

if __name__ == "__main__":
    import sys

    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
