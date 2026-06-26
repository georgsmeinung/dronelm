"""Pytest config shared by the airsim-plan test suite."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure `src/` is importable when pytest is run from the repo root without
# installing the package (so contributors can run tests immediately).
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
