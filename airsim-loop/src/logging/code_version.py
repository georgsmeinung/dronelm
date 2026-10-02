# Version del codigo de una corrida (2026-10-01).
#
# El hash de HEAD solo identifica el codigo si el arbol esta limpio. El piloto v3 193631Z corrio con
# cambios sin commitear (grilla 3x3, aceptacion del WP real, ...) y quedo con el mismo code_version
# que la corrida anterior, que usaba otro codigo: el criterio de descarte por code_version de los lotes
# (cap. 10 §10.12) no lo habria detectado. Con cambios sin commitear en el codigo, la configuracion o
# los manifiestos, la version lleva el sufijo "-dirty" y no coincide con la de ninguna corrida limpia.
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
# Lo que define el comportamiento de una corrida. Cambios en el informe o en docs/ no ensucian.
CODE_PATHS = ("airsim-loop", "config", "airsim-plan")


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ""


def get_code_version() -> str:
    try:
        head = _git("rev-parse", "--short", "HEAD")
        if not head:
            return "unknown"
        dirty = _git("status", "--porcelain", "--", *CODE_PATHS)
        return f"{head}-dirty" if dirty else head
    except Exception:
        return "unknown"
