"""Config de pytest compartida por la suite de tests de airsim-plan."""
from __future__ import annotations

import sys
from pathlib import Path

# Asegurar que `src/` sea importable cuando pytest corre desde la raíz del
# repo sin instalar el paquete (para que los colaboradores puedan correr los
# tests de inmediato).
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
