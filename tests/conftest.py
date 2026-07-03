import sys
from pathlib import Path

# Make the project root importable so tests can `import gapfinder` and `import gap_finder`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"
