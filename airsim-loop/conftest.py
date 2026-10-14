"""Pytest config: hace importable `src/` sin instalar el paquete."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _default_deadlock_strategy_blind(monkeypatch):
    """El test suite nunca debe depender del DEADLOCK_STRATEGY del .env local

    del desarrollador (2026-0901: .env de este entorno trae
    DEADLOCK_STRATEGY=deep_vlm por pedido explicito para pruebas de vuelo
    manuales -- sin este fixture, cualquier test escrito antes de H2 que
    ejercite el escape sincronico "a ciegas" se rompe en silencio segun quien
    lo corra). "blind" es el default explicito y estable para todo el suite;
    un test que quiera ejercitar deep_vlm lo pisa el mismo con su propio
    monkeypatch, como ya hacen tests/test_deep_scan.py.
    """
    monkeypatch.setenv("DEADLOCK_STRATEGY", "blind")
    import src.agents.deep_scan as deep_scan_mod

    monkeypatch.setattr(deep_scan_mod, "DEADLOCK_STRATEGY", "blind")
    # Idem STRATEGIC_SOURCE (2026-10-10): los tests del grafo se escriben con una capa estrategica activa
    # (la red de profundidad la stubea tests/conftest.py), sin importar el .env. Quien prueba off lo pisa.
    monkeypatch.setenv("STRATEGIC_SOURCE", "depth")
    import src.agents.vlm_strategic as vlm_strategic_mod

    monkeypatch.setattr(vlm_strategic_mod, "STRATEGIC_SOURCE", "depth")
