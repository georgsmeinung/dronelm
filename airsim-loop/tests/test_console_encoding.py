"""Los print() del codigo de ejecucion deben ser codificables en cp1252 (2026-0929).

El runner lanza cada corrida como subproceso con la salida por tuberia (cp1252 en Windows): un
`print` con una flecha o un simbolo fuera de cp1252 lanza UnicodeEncodeError. En land_smooth eso
cancelaba el aterrizaje suave del final de TODAS las corridas del runner (log del 2026-0929:
"Error en aterrizaje suave: 'charmap' codec can't encode character '\u2192'").
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prints_are_encodable_in_cp1252():
    files = list((ROOT / "src").rglob("*.py")) + [ROOT / "main.py", ROOT / "experiments" / "runner.py"]
    offenders = []
    for p in files:
        if "legacy" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        try:
                            sub.value.encode("cp1252")
                        except UnicodeEncodeError as exc:
                            offenders.append(f"{p.relative_to(ROOT)}:{sub.lineno} {sub.value[exc.start:exc.end]!r}")
    assert offenders == [], f"print con caracteres no codificables en cp1252: {offenders}"
